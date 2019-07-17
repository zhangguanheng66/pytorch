from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import numpy as np
import os
import shutil
import sys
import unittest

TEST_TENSORBOARD = True
try:
    import tensorboard.summary.writer.event_file_writer  # noqa F401
except ImportError:
    TEST_TENSORBOARD = False

HAS_TORCHVISION = True
try:
    import torchvision
except ImportError:
    HAS_TORCHVISION = False
skipIfNoTorchVision = unittest.skipIf(not HAS_TORCHVISION, "no torchvision")

TEST_CAFFE2 = True
try:
    from caffe2.python import workspace
except ImportError:
    TEST_CAFFE2 = False
skipIfNoCaffe2 = unittest.skipIf(not TEST_CAFFE2, "no caffe2")

TEST_MATPLOTLIB = True
try:
    import matplotlib
    if os.environ.get('DISPLAY', '') == '':
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    TEST_MATPLOTLIB = False
skipIfNoMatplotlib = unittest.skipIf(not TEST_MATPLOTLIB, "no matplotlib")

import torch
from common_utils import TestCase, run_tests

def tensor_N(shape, dtype=float):
    numel = np.prod(shape)
    x = (np.arange(numel, dtype=dtype)).reshape(shape)
    return x

class BaseTestCase(TestCase):
    """ Base class used for all TensorBoard tests """
    def tearDown(self):
        super(BaseTestCase, self).tearDown()
        if os.path.exists('runs'):
            # Remove directory created by SummaryWriter
            shutil.rmtree('runs')


if TEST_TENSORBOARD:
    from torch.utils.tensorboard import summary, SummaryWriter
    from torch.utils.tensorboard._utils import _prepare_video, convert_to_HWC
    from torch.utils.tensorboard._convert_np import make_np
    from torch.utils.tensorboard import _caffe2_graph as c2_graph
    from caffe2.python import brew, cnn, core, model_helper

    class TestTensorBoardPyTorchNumpy(BaseTestCase):
        def test_pytorch_np(self):
            tensors = [torch.rand(3, 10, 10), torch.rand(1), torch.rand(1, 2, 3, 4, 5)]
            for tensor in tensors:
                # regular tensor
                self.assertIsInstance(make_np(tensor), np.ndarray)

                # CUDA tensor
                if torch.cuda.device_count() > 0:
                    self.assertIsInstance(make_np(tensor.cuda()), np.ndarray)

                # regular variable
                self.assertIsInstance(make_np(torch.autograd.Variable(tensor)), np.ndarray)

                # CUDA variable
                if torch.cuda.device_count() > 0:
                    self.assertIsInstance(make_np(torch.autograd.Variable(tensor).cuda()), np.ndarray)

            # python primitive type
            self.assertIsInstance(make_np(0), np.ndarray)
            self.assertIsInstance(make_np(0.1), np.ndarray)

        def test_pytorch_autograd_np(self):
            x = torch.autograd.Variable(torch.Tensor(1))
            self.assertIsInstance(make_np(x), np.ndarray)

        def test_pytorch_write(self):
            with SummaryWriter() as w:
                w.add_scalar('scalar', torch.autograd.Variable(torch.rand(1)), 0)

        def test_pytorch_histogram(self):
            with SummaryWriter() as w:
                w.add_histogram('float histogram', torch.rand((50,)))
                w.add_histogram('int histogram', torch.randint(0, 100, (50,)))

        def test_pytorch_histogram_raw(self):
            with SummaryWriter() as w:
                num = 50
                floats = make_np(torch.rand((num,)))
                bins = [0.0, 0.25, 0.5, 0.75, 1.0]
                counts, limits = np.histogram(floats, bins)
                sum_sq = floats.dot(floats).item()
                w.add_histogram_raw('float histogram raw',
                                    min=floats.min().item(),
                                    max=floats.max().item(),
                                    num=num,
                                    sum=floats.sum().item(),
                                    sum_squares=sum_sq,
                                    bucket_limits=limits[1:].tolist(),
                                    bucket_counts=counts.tolist())

                ints = make_np(torch.randint(0, 100, (num,)))
                bins = [0, 25, 50, 75, 100]
                counts, limits = np.histogram(ints, bins)
                sum_sq = ints.dot(ints).item()
                w.add_histogram_raw('int histogram raw',
                                    min=ints.min().item(),
                                    max=ints.max().item(),
                                    num=num,
                                    sum=ints.sum().item(),
                                    sum_squares=sum_sq,
                                    bucket_limits=limits[1:].tolist(),
                                    bucket_counts=counts.tolist())

                ints = torch.tensor(range(0, 100)).float()
                nbins = 100
                counts = torch.histc(ints, bins=nbins, min=0, max=99)
                limits = torch.tensor(range(nbins))
                sum_sq = ints.dot(ints).item()
                w.add_histogram_raw('int histogram raw',
                                    min=ints.min().item(),
                                    max=ints.max().item(),
                                    num=num,
                                    sum=ints.sum().item(),
                                    sum_squares=sum_sq,
                                    bucket_limits=limits.tolist(),
                                    bucket_counts=counts.tolist())

    class TestTensorBoardUtils(BaseTestCase):
        def test_to_HWC(self):
            test_image = np.random.randint(0, 256, size=(3, 32, 32), dtype=np.uint8)
            converted = convert_to_HWC(test_image, 'chw')
            self.assertEqual(converted.shape, (32, 32, 3))
            test_image = np.random.randint(0, 256, size=(16, 3, 32, 32), dtype=np.uint8)
            converted = convert_to_HWC(test_image, 'nchw')
            self.assertEqual(converted.shape, (64, 256, 3))
            test_image = np.random.randint(0, 256, size=(32, 32), dtype=np.uint8)
            converted = convert_to_HWC(test_image, 'hw')
            self.assertEqual(converted.shape, (32, 32, 3))

        def test_prepare_video(self):
            # At each timeframe, the sum over all other
            # dimensions of the video should be the same.
            shapes = [(16, 30, 3, 28, 28),
                      (36, 30, 3, 28, 28),
                      (19, 29, 3, 23, 19),
                      (3, 3, 3, 3, 3)]
            for s in shapes:
                V_input = np.random.random(s)
                V_after = _prepare_video(np.copy(V_input))
                total_frame = s[1]
                V_input = np.swapaxes(V_input, 0, 1)
                for f in range(total_frame):
                    x = np.reshape(V_input[f], newshape=(-1))
                    y = np.reshape(V_after[f], newshape=(-1))
                    np.testing.assert_array_almost_equal(np.sum(x), np.sum(y))

        def test_numpy_vid_uint8(self):
            V_input = np.random.randint(0, 256, (16, 30, 3, 28, 28)).astype(np.uint8)
            V_after = _prepare_video(np.copy(V_input)) * 255
            total_frame = V_input.shape[1]
            V_input = np.swapaxes(V_input, 0, 1)
            for f in range(total_frame):
                x = np.reshape(V_input[f], newshape=(-1))
                y = np.reshape(V_after[f], newshape=(-1))
                np.testing.assert_array_almost_equal(np.sum(x), np.sum(y))

    freqs = [262, 294, 330, 349, 392, 440, 440, 440, 440, 440, 440]

    true_positive_counts = [75, 64, 21, 5, 0]
    false_positive_counts = [150, 105, 18, 0, 0]
    true_negative_counts = [0, 45, 132, 150, 150]
    false_negative_counts = [0, 11, 54, 70, 75]
    precision = [0.3333333, 0.3786982, 0.5384616, 1.0, 0.0]
    recall = [1.0, 0.8533334, 0.28, 0.0666667, 0.0]

    class TestTensorBoardWriter(BaseTestCase):
        def test_writer(self):
            with SummaryWriter() as writer:
                sample_rate = 44100

                n_iter = 0
                writer.add_scalar('data/scalar_systemtime', 0.1, n_iter)
                writer.add_scalar('data/scalar_customtime', 0.2, n_iter, walltime=n_iter)
                writer.add_scalars('data/scalar_group', {"xsinx": n_iter * np.sin(n_iter),
                                                         "xcosx": n_iter * np.cos(n_iter),
                                                         "arctanx": np.arctan(n_iter)}, n_iter)
                x = np.zeros((32, 3, 64, 64))  # output from network
                writer.add_images('Image', x, n_iter)  # Tensor
                writer.add_image_with_boxes('imagebox',
                                            np.zeros((3, 64, 64)),
                                            np.array([[10, 10, 40, 40], [40, 40, 60, 60]]),
                                            n_iter)
                x = np.zeros(sample_rate * 2)

                writer.add_audio('myAudio', x, n_iter)
                writer.add_video('myVideo', np.random.rand(16, 48, 1, 28, 28).astype(np.float32), n_iter)
                writer.add_text('Text', 'text logged at step:' + str(n_iter), n_iter)
                writer.add_text('markdown Text', '''a|b\n-|-\nc|d''', n_iter)
                writer.add_histogram('hist', np.random.rand(100, 100), n_iter)
                writer.add_pr_curve('xoxo', np.random.randint(2, size=100), np.random.rand(
                    100), n_iter)  # needs tensorboard 0.4RC or later
                writer.add_pr_curve_raw('prcurve with raw data', true_positive_counts,
                                        false_positive_counts,
                                        true_negative_counts,
                                        false_negative_counts,
                                        precision,
                                        recall, n_iter)

    class TestTensorBoardSummaryWriter(BaseTestCase):
        def test_summary_writer_ctx(self):
            # after using a SummaryWriter as a ctx it should be closed
            with SummaryWriter(filename_suffix='.test') as writer:
                writer.add_scalar('test', 1)
            self.assertIs(writer.file_writer, None)

        def test_summary_writer_close(self):
            # Opening and closing SummaryWriter a lot should not run into
            # OSError: [Errno 24] Too many open files
            passed = True
            try:
                writer = SummaryWriter()
                writer.close()
            except OSError:
                passed = False

            self.assertTrue(passed)

        def test_pathlib(self):
            import sys
            if sys.version_info.major == 2:
                import pathlib2 as pathlib
            else:
                import pathlib
            p = pathlib.Path('./pathlibtest')
            with SummaryWriter(p) as writer:
                writer.add_scalar('test', 1)
            import shutil
            shutil.rmtree(str(p))

    class TestTensorBoardEmbedding(BaseTestCase):
        def test_embedding(self):
            w = SummaryWriter()
            all_features = torch.Tensor([[1, 2, 3], [5, 4, 1], [3, 7, 7]])
            all_labels = torch.Tensor([33, 44, 55])
            all_images = torch.zeros(3, 3, 5, 5)

            w.add_embedding(all_features,
                            metadata=all_labels,
                            label_img=all_images,
                            global_step=2)

            dataset_label = ['test'] * 2 + ['train'] * 2
            all_labels = list(zip(all_labels, dataset_label))
            w.add_embedding(all_features,
                            metadata=all_labels,
                            label_img=all_images,
                            metadata_header=['digit', 'dataset'],
                            global_step=2)
            # assert...

        def test_embedding_64(self):
            w = SummaryWriter()
            all_features = torch.Tensor([[1, 2, 3], [5, 4, 1], [3, 7, 7]])
            all_labels = torch.Tensor([33, 44, 55])
            all_images = torch.zeros((3, 3, 5, 5), dtype=torch.float64)

            w.add_embedding(all_features,
                            metadata=all_labels,
                            label_img=all_images,
                            global_step=2)

            dataset_label = ['test'] * 2 + ['train'] * 2
            all_labels = list(zip(all_labels, dataset_label))
            w.add_embedding(all_features,
                            metadata=all_labels,
                            label_img=all_images,
                            metadata_header=['digit', 'dataset'],
                            global_step=2)

    class TestTensorBoardSummary(BaseTestCase):
        def test_uint8_image(self):
            '''
            Tests that uint8 image (pixel values in [0, 255]) is not changed
            '''
            test_image = np.random.randint(0, 256, size=(3, 32, 32), dtype=np.uint8)
            scale_factor = summary._calc_scale_factor(test_image)
            self.assertEqual(scale_factor, 1, 'Values are already in [0, 255], scale factor should be 1')

        def test_float32_image(self):
            '''
            Tests that float32 image (pixel values in [0, 1]) are scaled correctly
            to [0, 255]
            '''
            test_image = np.random.rand(3, 32, 32).astype(np.float32)
            scale_factor = summary._calc_scale_factor(test_image)
            self.assertEqual(scale_factor, 255, 'Values are in [0, 1], scale factor should be 255')

        def test_list_input(self):
            with self.assertRaises(Exception) as e_info:
                summary.histogram('dummy', [1, 3, 4, 5, 6], 'tensorflow')

        def test_empty_input(self):
            with self.assertRaises(Exception) as e_info:
                summary.histogram('dummy', np.ndarray(0), 'tensorflow')

        def test_image_with_boxes(self):
            self.assertTrue(compare_proto(summary.image_boxes('dummy',
                                          tensor_N(shape=(3, 32, 32)),
                                          np.array([[10, 10, 40, 40]])),
                                          self))

        def test_image_with_one_channel(self):
            self.assertTrue(compare_proto(summary.image('dummy',
                                                        tensor_N(shape=(1, 8, 8)),
                                                        dataformats='CHW'),
                                                        self))  # noqa E127

        def test_image_with_one_channel_batched(self):
            self.assertTrue(compare_proto(summary.image('dummy',
                                                        tensor_N(shape=(2, 1, 8, 8)),
                                                        dataformats='NCHW'),
                                                        self))  # noqa E127

        def test_image_with_3_channel_batched(self):
            self.assertTrue(compare_proto(summary.image('dummy',
                                                        tensor_N(shape=(2, 3, 8, 8)),
                                                        dataformats='NCHW'),
                                                        self))  # noqa E127

        def test_image_without_channel(self):
            self.assertTrue(compare_proto(summary.image('dummy',
                                                        tensor_N(shape=(8, 8)),
                                                        dataformats='HW'),
                                                        self))  # noqa E127

        def test_video(self):
            try:
                import moviepy  # noqa F401
            except ImportError:
                return
            self.assertTrue(compare_proto(summary.video('dummy', tensor_N(shape=(4, 3, 1, 8, 8))), self))
            summary.video('dummy', np.random.rand(16, 48, 1, 28, 28))
            summary.video('dummy', np.random.rand(20, 7, 1, 8, 8))

        def test_audio(self):
            self.assertTrue(compare_proto(summary.audio('dummy', tensor_N(shape=(42,))), self))

        def test_text(self):
            self.assertTrue(compare_proto(summary.text('dummy', 'text 123'), self))

        def test_histogram_auto(self):
            self.assertTrue(compare_proto(summary.histogram('dummy', tensor_N(shape=(1024,)), bins='auto', max_bins=5), self))

        def test_histogram_fd(self):
            self.assertTrue(compare_proto(summary.histogram('dummy', tensor_N(shape=(1024,)), bins='fd', max_bins=5), self))

        def test_histogram_doane(self):
            self.assertTrue(compare_proto(summary.histogram('dummy', tensor_N(shape=(1024,)), bins='doane', max_bins=5), self))

        def test_custom_scalars(self):
            layout = {'Taiwan': {'twse': ['Multiline', ['twse/0050', 'twse/2330']]},
                      'USA': {'dow': ['Margin', ['dow/aaa', 'dow/bbb', 'dow/ccc']],
                              'nasdaq': ['Margin', ['nasdaq/aaa', 'nasdaq/bbb', 'nasdaq/ccc']]}}
            summary.custom_scalars(layout)  # only smoke test. Because protobuf in python2/3 serialize dictionary differently.

    def remove_whitespace(string):
        return string.replace(' ', '').replace('\t', '').replace('\n', '')

    def compare_proto(str_to_compare, function_ptr):

        module_id = function_ptr.__class__.__module__
        test_dir = os.path.dirname(sys.modules[module_id].__file__)
        functionName = function_ptr.id().split('.')[-1]
        expected_file = os.path.join(test_dir,
                                     "expect",
                                     'TestTensorBoard.' + functionName + ".expect")

        assert os.path.exists(expected_file)
        with open(expected_file) as f:
            expected = f.read()
        str_to_compare = str(str_to_compare)
        # if not remove_whitespace(str_to_compare) == remove_whitespace(expected):
        return remove_whitespace(str_to_compare) == remove_whitespace(expected)

    def write_proto(str_to_compare, function_ptr):
        module_id = function_ptr.__class__.__module__
        test_dir = os.path.dirname(sys.modules[module_id].__file__)
        functionName = function_ptr.id().split('.')[-1]
        expected_file = os.path.join(test_dir,
                                     "expect",
                                     'TestTensorBoard.' + functionName + ".expect")
        with open(expected_file, 'w') as f:
            f.write(str(str_to_compare))

    class TestTensorBoardPytorchGraph(BaseTestCase):
        def test_pytorch_graph(self):
            dummy_input = (torch.zeros(1, 3),)

            class myLinear(torch.nn.Module):
                def __init__(self):
                    super(myLinear, self).__init__()
                    self.l = torch.nn.Linear(3, 5)

                def forward(self, x):
                    return self.l(x)

            with SummaryWriter(comment='LinearModel') as w:
                w.add_graph(myLinear(), dummy_input)

        def test_mlp_graph(self):
            dummy_input = (torch.zeros(2, 1, 28, 28),)

            # This MLP class with the above input is expected
            # to fail JIT optimizations as seen at
            # https://github.com/pytorch/pytorch/issues/18903
            #
            # However, it should not raise an error during
            # the add_graph call and still continue.
            class myMLP(torch.nn.Module):
                def __init__(self):
                    super(myMLP, self).__init__()
                    self.input_len = 1 * 28 * 28
                    self.fc1 = torch.nn.Linear(self.input_len, 1200)
                    self.fc2 = torch.nn.Linear(1200, 1200)
                    self.fc3 = torch.nn.Linear(1200, 10)

                def forward(self, x, update_batch_stats=True):
                    h = torch.nn.functional.relu(
                        self.fc1(x.view(-1, self.input_len)))
                    h = self.fc2(h)
                    h = torch.nn.functional.relu(h)
                    h = self.fc3(h)
                    return h

            with SummaryWriter(comment='MLPModel') as w:
                w.add_graph(myMLP(), dummy_input)

        def test_wrong_input_size(self):
            with self.assertRaises(RuntimeError) as e_info:
                dummy_input = torch.rand(1, 9)
                model = torch.nn.Linear(3, 5)
                with SummaryWriter(comment='expect_error') as w:
                    w.add_graph(model, dummy_input)  # error

        @skipIfNoTorchVision
        def test_torchvision_smoke(self):
            model_input_shapes = {
                'alexnet': (2, 3, 224, 224),
                'resnet34': (2, 3, 224, 224),
                'resnet152': (2, 3, 224, 224),
                'densenet121': (2, 3, 224, 224),
                'vgg16': (2, 3, 224, 224),
                'vgg19': (2, 3, 224, 224),
                'vgg16_bn': (2, 3, 224, 224),
                'vgg19_bn': (2, 3, 224, 224),
                'mobilenet_v2': (2, 3, 224, 224),
            }
            for model_name, input_shape in model_input_shapes.items():
                with SummaryWriter(comment=model_name) as w:
                    model = getattr(torchvision.models, model_name)()
                    w.add_graph(model, torch.zeros(input_shape))

    class TestTensorBoardFigure(BaseTestCase):
        @skipIfNoMatplotlib
        def test_figure(self):
            writer = SummaryWriter()

            figure, axes = plt.figure(), plt.gca()
            circle1 = plt.Circle((0.2, 0.5), 0.2, color='r')
            circle2 = plt.Circle((0.8, 0.5), 0.2, color='g')
            axes.add_patch(circle1)
            axes.add_patch(circle2)
            plt.axis('scaled')
            plt.tight_layout()

            writer.add_figure("add_figure/figure", figure, 0, close=False)
            self.assertTrue(plt.fignum_exists(figure.number))

            writer.add_figure("add_figure/figure", figure, 1)
            self.assertFalse(plt.fignum_exists(figure.number))

            writer.close()

        @skipIfNoMatplotlib
        def test_figure_list(self):
            writer = SummaryWriter()

            figures = []
            for i in range(5):
                figure = plt.figure()
                plt.plot([i * 1, i * 2, i * 3], label="Plot " + str(i))
                plt.xlabel("X")
                plt.xlabel("Y")
                plt.legend()
                plt.tight_layout()
                figures.append(figure)

            writer.add_figure("add_figure/figure_list", figures, 0, close=False)
            self.assertTrue(all([plt.fignum_exists(figure.number) is True for figure in figures]))  # noqa F812

            writer.add_figure("add_figure/figure_list", figures, 1)
            self.assertTrue(all([plt.fignum_exists(figure.number) is False for figure in figures]))  # noqa F812

            writer.close()

    class TestTensorBoardNumpy(BaseTestCase):
        def test_scalar(self):
            res = make_np(1.1)
            self.assertIsInstance(res, np.ndarray) and self.assertEqual(res.shape, (1,))
            res = make_np(1 << 64 - 1)  # uint64_max
            self.assertIsInstance(res, np.ndarray) and self.assertEqual(res.shape, (1,))
            res = make_np(np.float16(1.00000087))
            self.assertIsInstance(res, np.ndarray) and self.assertEqual(res.shape, (1,))
            res = make_np(np.float128(1.00008 + 9))
            self.assertIsInstance(res, np.ndarray) and self.assertEqual(res.shape, (1,))
            res = make_np(np.int64(100000000000))
            self.assertIsInstance(res, np.ndarray) and self.assertEqual(res.shape, (1,))

        @skipIfNoCaffe2
        def test_caffe2_np(self):
            workspace.FeedBlob("testBlob", tensor_N(shape=(1, 3, 64, 64)))
            self.assertIsInstance(make_np('testBlob'), np.ndarray)

        @skipIfNoCaffe2
        def test_caffe2_np_expect_fail(self):
            with self.assertRaises(RuntimeError):
                res = make_np('This_blob_does_not_exist')

        def test_pytorch_np_expect_fail(self):
            with self.assertRaises(NotImplementedError):
                res = make_np({'pytorch': 1.0})

        def test_simple_model(self):
            model = model_helper.ModelHelper(name="mnist")
            # how come those inputs don't break the forward pass =.=a
            workspace.FeedBlob("data", np.random.randn(1, 3, 64, 64).astype(np.float32))
            workspace.FeedBlob("label", np.random.randn(1, 1000).astype(np.int))

            with core.NameScope("conv1"):
                conv1 = brew.conv(model, "data", 'conv1', dim_in=1, dim_out=20, kernel=5)
                # Image size: 24 x 24 -> 12 x 12
                pool1 = brew.max_pool(model, conv1, 'pool1', kernel=2, stride=2)
                # Image size: 12 x 12 -> 8 x 8
                conv2 = brew.conv(model, pool1, 'conv2', dim_in=20, dim_out=100, kernel=5)
                # Image size: 8 x 8 -> 4 x 4
                pool2 = brew.max_pool(model, conv2, 'pool2', kernel=2, stride=2)
            with core.NameScope("classifier"):
                # 50 * 4 * 4 stands for dim_out from previous layer multiplied by the image size
                fc3 = brew.fc(model, pool2, 'fc3', dim_in=100 * 4 * 4, dim_out=500)
                relu = brew.relu(model, fc3, fc3)
                pred = brew.fc(model, relu, 'pred', 500, 10)
                softmax = brew.softmax(model, pred, 'softmax')
                xent = model.LabelCrossEntropy([softmax, "label"], 'xent')
                # compute the expected loss
                loss = model.AveragedLoss(xent, "loss")
            model.net.RunAllOnMKL()
            model.param_init_net.RunAllOnMKL()
            model.AddGradientOperators([loss], skip=1)
            blob_name_tracker = {}
            graph = c2_graph.model_to_graph_def(
                model,
                blob_name_tracker=blob_name_tracker,
                shapes={},
                show_simplified=False,
            )
            compare_proto(graph, self)

        def test_simple_cnnmodel(self):
            model = cnn.CNNModelHelper("NCHW", name="overfeat")
            workspace.FeedBlob("data", np.random.randn(1, 3, 64, 64).astype(np.float32))
            workspace.FeedBlob("label", np.random.randn(1, 1000).astype(np.int))
            with core.NameScope("conv1"):
                conv1 = model.Conv("data", "conv1", 3, 96, 11, stride=4)
                relu1 = model.Relu(conv1, conv1)
                pool1 = model.MaxPool(relu1, "pool1", kernel=2, stride=2)
            with core.NameScope("classifier"):
                fc = model.FC(pool1, "fc", 4096, 1000)
                pred = model.Softmax(fc, "pred")
                xent = model.LabelCrossEntropy([pred, "label"], "xent")
                loss = model.AveragedLoss(xent, "loss")

            blob_name_tracker = {}
            graph = c2_graph.model_to_graph_def(
                model,
                blob_name_tracker=blob_name_tracker,
                shapes={},
                show_simplified=False,
            )
            compare_proto(graph, self)

if __name__ == '__main__':
    run_tests()
