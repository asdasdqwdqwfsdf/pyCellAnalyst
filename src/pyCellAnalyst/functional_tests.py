import unittest
import tempfile
import shutil
import os

import pyCellAnalyst
import SimpleITK as sitk
import vtk
import numpy as np

def transformBaseImage(image, displacements, noiseLevel):
    size = [int(np.ceil(i / 2.0)) for i in image.GetSize()]
    padded = sitk.ConstantPad(image, size, size, 0.0)
    tx = sitk.BSplineTransformInitializer(padded, [2] * padded.GetDimension(), 1)
    tx.SetParameters(displacements)
    newimage = sitk.Resample(padded, tx, sitk.sitkLinear)
    mask = sitk.BinaryThreshold(newimage, 0.5, 1e3)
    ls = sitk.LabelShapeStatisticsImageFilter()
    ls.Execute(mask)
    bb = ls.GetBoundingBox(1)
    dim = newimage.GetDimension()
    #pad bounding box by 2 voxels
    origin = [i-2 for i in bb[0:dim]]
    size = [i+4 for i in bb[dim:]]
    #Crop padded image to include deformed cells
    image = sitk.RegionOfInterest(newimage, size, origin)
    image = sitk.AdditiveGaussianNoise(image, standardDeviation=noiseLevel)
    image = sitk.RescaleIntensity(image, 0.0, 1.0)

    mask = sitk.RegionOfInterest(mask, size, origin)
    # Find the object subregions
    labels = sitk.ConnectedComponent(mask)
    ls.Execute(labels)
    regions = []
    for l in ls.GetLabels():
        bb = ls.GetBoundingBox(l)
        origin = [i-2 for i in bb[0:dim]]
        size = [i+4 for i in bb[dim:]]
        regions.append(origin + size)
    return image, regions

def generateSuperEllipsoid(A, B, C, r, t, spacing):
    """
    generate the base image
    using super-ellipsoid to represent pseudo-cells
    [(|x / A|)^r + (|y / B|)^r]^( t / r) + (|z / C|)^t <= 1
    """
    steps = np.array([2*(A + spacing[0]),
                      2*(B + spacing[1]),
                      2*(C + spacing[2])]) / np.array(spacing)
    # this is reversed due to ordering difference of SimpleITK and numpy
    grid = np.meshgrid(np.linspace(-C - spacing[2], C + spacing[2], num=steps[2]),
                       np.linspace(-B - spacing[1], B + spacing[1], num=steps[1]),
                       np.linspace(-A - spacing[0], A + spacing[0], num=steps[0]), indexing='ij')

    f = (np.abs(grid[2] / A)**r + np.abs(grid[1] / B)**r)**(t / r) + np.abs(grid[0] / C)**t
    f = f <= 1
    return f.astype(np.float32)

def generateTestImages(n=1, deformed=False, noiseLevel=0.3):
    n = int(n)

    spacing = [0.25, 0.25, 0.25]
    # Cell 1:
    # A = 4
    # B = 5
    # C = 2
    # r = 2
    # t = 2.5
    cell1 = generateSuperEllipsoid(4, 5, 2, 2, 2.5, spacing)
    image1 = sitk.GetImageFromArray(cell1)
    image1.SetOrigin([0.0, 0.0, 0.0])
    image1.SetSpacing(spacing)

    # Cell 2:
    # A = 5
    # B = 6
    # C = 2.5
    # r = 2
    # t = 3.0
    cell2 = generateSuperEllipsoid(5, 6, 2.5, 2, 3.0, spacing)
    image2 = sitk.GetImageFromArray(cell2)
    image2.SetOrigin([0.0, 0.0, 0.0])
    image2.SetSpacing(spacing)

    image = sitk.Tile([image1, image2], [2,1,1])

    parent_dir = tempfile.mkdtemp()
    allregions = {"reference": [], "deformed": []}
    for i in range(n):
        displacements = np.random.normal(0.0, 1.0, 91)
        reference, regions = transformBaseImage(image, displacements, noiseLevel)
        image_path = os.path.join(parent_dir, "ref{:d}".format(i+1))
        os.mkdir(image_path)
        sitk.WriteImage(reference, os.path.join(image_path, "img.nii"))
        allregions["reference"].append(regions)
        if deformed:
            displacements2 = np.random.normal(0.0, 1.0, 91)
            deformed, regions = transformBaseImage(reference, displacements2, noiseLevel)
            image_path = os.path.join(parent_dir, "def{:d}".format(i+1))
            os.mkdir(image_path)
            sitk.WriteImage(deformed, os.path.join(image_path, "img.nii"))
            allregions["deformed"].append(regions)
    return parent_dir, allregions

class ImageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._imageRootDir, cls._regions = generateTestImages(n=1, noiseLevel=0.5)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._imageRootDir)

    def setUp(self):
        self.im = pyCellAnalyst.FloatImage(os.path.join(self._imageRootDir, 'ref1', 'img.nii'), spacing=[0.25, 0.25, 0.25])

    def test_image_from_file(self):
        self.assertIsInstance(self.im, pyCellAnalyst.Image)
        # test that spacing can be set after instantiation
        self.im.spacing = [1.0, 1.0, 1.0]
        # here we try to set the spacing incorrectly for 3d image; if an error isn't thrown, test fails
        try:
            self.im.spacing=[1.0, 1.0]
            self.fail()
        except:
            pass

    def test_image_from_stack(self):
        # create an image stack
        tmp_dir = tempfile.mkdtemp()
        size = self.im.image.GetSize()
        for i in range(size[2]):
            islice = sitk.Extract(self.im.image, [size[0], size[1], 0], [0, 0, i])
            sitk.WriteImage(islice, os.path.join(tmp_dir, 'slice{:03d}.tif'.format(i)))
        im = pyCellAnalyst.FloatImage(tmp_dir, spacing=[0.25, 0.25, 0.25])
        self.assertIsInstance(im, pyCellAnalyst.Image)
        shutil.rmtree(tmp_dir)

    def test_image_to_and_from_numpy(self):
        self.im.convertToNumpy()
        self.assertIsInstance(self.im.numpyimage, np.ndarray)
        im2 = pyCellAnalyst.FloatImage(self.im.numpyimage, spacing=[0.25, 0.25, 0.25])
        self.assertIsInstance(im2, pyCellAnalyst.Image)

    def test_image_to_vtk(self):
        vtk_filepath = os.path.join(self._imageRootDir, 'img')
        self.im.writeAsVTK(name=vtk_filepath)
        self.assertTrue(os.path.isfile('.'.join([vtk_filepath, 'vti'])))

    def test_invert_image(self):
        self.im.invert()

    def test_filter_gaussian(self):
        f = pyCellAnalyst.Gaussian(inputImage=self.im)
        f.parameters['variance'] = 1.0
        f.execute()

    def test_filter_curvature_anisotropic_diffusion(self):
        f = pyCellAnalyst.CurvatureAnisotropicDiffusion(inputImage=self.im)
        f.parameters['iterations'] = 15
        f.parameters['conductance'] = 10
        f.execute()

    def test_filter_gradient_anisotropic_diffusion(self):
        f = pyCellAnalyst.GradientAnisotropicDiffusion(inputImage=self.im)
        f.parameters['iterations'] = 15
        f.parameters['conductance'] = 10
        f.parameters['time_step'] = 0.02
        f.execute()

    def test_filter_bilateral(self):
        f = pyCellAnalyst.Bilateral(inputImage=self.im)
        f.parameters['domainSigma'] = 0.2
        f.parameters['rangeSigma'] = 5.0
        f.parameters['numberOfRangeGaussianSamples'] = 50
        f.execute()

    def test_filter_patchbased_denoising(self):
        f = pyCellAnalyst.PatchBasedDenoising(inputImage=self.im)
        f.parameters['radius'] = 2
        f.parameters['patches'] = 10
        f.parameters['iterations'] = 2
        f.parameters['noise_model'] = 'gaussian'
        f.execute()

    def test_filter_enhance_edges(self):
        f = pyCellAnalyst.EnhanceEdges(inputImage=self.im)
        f.execute()

    def test_filtering_pipeline(self):
        p = pyCellAnalyst.FilteringPipeline(inputImage=self.im)
        p.addFilter(pyCellAnalyst.CurvatureAnisotropicDiffusion(iterations=10))
        p.addFilter(pyCellAnalyst.EnhanceEdges())
        p.execute()

    def test_regions_of_interest(self):
        rois = pyCellAnalyst.RegionsOfInterest(inputImage=self.im, regions_of_interest=self._regions["reference"][0])
        for i in rois.images:
            self.assertIsInstance(i, type(self.im))

    def test_slice_viewer(self):
        f = pyCellAnalyst.CurvatureAnisotropicDiffusion(inputImage=self.im, iterations=20)
        f.execute()
        sv = pyCellAnalyst.SliceViewer([self.im, f.outputImage], titles=['Original', 'CurvatureAnisotropicDiffusion'])
        sv.view()

class SegmentationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._imageRootDir, cls._regions = generateTestImages(n=1, noiseLevel=0.5)
        cls._im = pyCellAnalyst.FloatImage(os.path.join(cls._imageRootDir, 'ref1', 'img.nii'), spacing=[0.25, 0.25, 0.25])
        cls._roi = pyCellAnalyst.RegionsOfInterest(inputImage=cls._im, regions_of_interest=cls._regions["reference"][0])
        cls._smooth_images = []
        for i in cls._roi.images:
            f = pyCellAnalyst.CurvatureAnisotropicDiffusion(inputImage=i, iterations=50)
            f.execute()
            cls._smooth_images.append(f.outputImage)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._imageRootDir)

    def test_threshold_methods(self):
        segs = []
        titles = []
        for c in pyCellAnalyst.Threshold.__subclasses__():
            thres = c(inputImage=self._smooth_images[0])
            thres.execute()
            titles.append(c.__name__)
            segs.append(thres.outputImage)

        sv = pyCellAnalyst.SliceViewer(inputImages=segs, titles=titles)
        sv.view()

    def test_threshold_two_pass(self):
        otsu = pyCellAnalyst.Otsu(inputImage=self._smooth_images[0], objectID=3)
        otsu.execute()

        otsu2 = pyCellAnalyst.Otsu(inputImage=self._smooth_images[0], mask=otsu.outputImage)
        otsu2.execute()
        sv = pyCellAnalyst.SliceViewer(inputImages=[self._roi.images[0], otsu.outputImage, otsu2.outputImage], titles=['Original', 'Otsu 1st Pass', 'Otsu Second Pass'])
        sv.view()

    def test_geodesic_active_contour(self):
        s1 = pyCellAnalyst.GeodesicActiveContour(inputImage=self._smooth_images[0], curvatureScaling=0.5, advectionScaling=1.0)
        s1.execute()

        # test using a thresholded image as seed. SimpleITK used directly to eliminate dependence on other tested features.
        segs = []
        seeds = [pyCellAnalyst.EightBitImage(sitk.OtsuThreshold(i.image, 0, 1), spacing=i.spacing) for i in self._smooth_images]
        for i, s in enumerate(seeds):
            s2 = pyCellAnalyst.GeodesicActiveContour(inputImage=self._smooth_images[i], seed=s)
            s2.execute()
            segs.append(s2.outputImage)

            writer = vtk.vtkPolyDataWriter()
            writer.SetFileName('geodesic{}.vtk'.format(i+1))
            writer.SetInputData(s2.isocontour)
            writer.Write()

        sv = pyCellAnalyst.SliceViewer(inputImages=self._roi.images + [s1.outputImage] + segs , titles=['Original 1', 'Original 2', 'No seed', 'Otsu Seed 1', 'Otsu Seed 2'])
        sv.view()

    def test_visualize_isosurfaces(self):
        pass

class DeformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def test_surface_from_file(self):
        pass

    def test_surfaces_from_filelist(self):
        pass

    def test_surfaces_from_directory(self):
        pass

    def test_surfaces_from_memory(self):
        pass

    def test_ellipsoidal_method(self):
        pass

    def test_affine_transformation_method(self):
        pass

    def test_diffeomorphic_demons_method(self):
        pass

    def test_visualize_displacements(self):
        pass

if __name__ == '__main__':
    unittest.main()
