# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import os
import tempfile

import mxnet as mx
from mxnet import gluon
from mxnet.gluon import nn
from mxnet.test_utils import assert_almost_equal
from mxnet.ndarray.ndarray import _STORAGE_TYPE_STR_TO_ID
from common import (setup_module, with_seed, assertRaises, teardown,
                    assert_raises_cudnn_not_satisfied)
import numpy as np
from numpy.testing import assert_array_equal
from nose.tools import raises, assert_raises
from copy import deepcopy
import warnings
import json
import unittest

@with_seed()
def test_parameter():
    p = gluon.Parameter('weight', shape=(10, 10))
    p.initialize(init='xavier', ctx=[mx.cpu(0), mx.cpu(1)])
    assert len(p.list_data()) == 2
    assert len(p.list_grad()) == 2
    assert p.data(mx.cpu(1)).context == mx.cpu(1)
    assert p.data(mx.cpu(0)).shape == (10, 10)
    assert p.var().name == 'weight'
    assert p.grad(mx.cpu(0)).stype == 'default'
    assert p.data(mx.cpu(0)).stype == 'default'

    p.reset_ctx(ctx=[mx.cpu(1), mx.cpu(2)])
    assert p.list_ctx() == [mx.cpu(1), mx.cpu(2)]

@with_seed()
@raises(AssertionError)
def test_invalid_parameter_stype():
    p = gluon.Parameter('weight', shape=(10, 10), stype='invalid')

@with_seed()
@raises(AssertionError)
def test_invalid_parameter_grad_stype():
    p = gluon.Parameter('weight', shape=(10, 10), grad_stype='invalid')

@with_seed()
def test_sparse_parameter():
    p = gluon.Parameter('weight', shape=(10, 10), stype='row_sparse', grad_stype='row_sparse')
    p.initialize(init='xavier', ctx=[mx.cpu(0), mx.cpu(1)])
    row_id = mx.nd.arange(0, 10, ctx=mx.cpu(1))
    assert len(p.list_grad()) == 2
    # getting row_sparse data without trainer throws an exception
    assertRaises(RuntimeError, p.list_row_sparse_data, row_id)
    trainer = mx.gluon.Trainer([p], 'sgd')
    assert len(p.list_row_sparse_data(row_id)) == 2
    weight = p.row_sparse_data(row_id)
    assert weight.context == mx.cpu(1)
    assert weight.shape == (10, 10)
    assert weight.stype == 'row_sparse'
    assert p.var().name == 'weight'
    assert p.var().attr('__storage_type__') == str(_STORAGE_TYPE_STR_TO_ID['row_sparse'])
    assert p.grad(mx.cpu(0)).stype == 'row_sparse'

    p.reset_ctx(ctx=[mx.cpu(1), mx.cpu(2)])
    assert p.list_ctx() == [mx.cpu(1), mx.cpu(2)]

@with_seed()
def test_parameter_invalid_access():
    # cannot call data on row_sparse parameters
    p0 = gluon.Parameter('weight', shape=(10, 10), stype='row_sparse', grad_stype='row_sparse')
    p0.initialize(init='xavier', ctx=[mx.cpu(0), mx.cpu(1)])
    assertRaises(RuntimeError, p0.data)
    assertRaises(RuntimeError, p0.list_data)
    row_id = mx.nd.arange(0, 10)
    # cannot call row_sparse_data on dense parameters
    p1 = gluon.Parameter('weight', shape=(10, 10))
    p1.initialize(init='xavier', ctx=[mx.cpu(0), mx.cpu(1)])
    assertRaises(RuntimeError, p1.row_sparse_data, row_id.copyto(mx.cpu(0)))
    assertRaises(RuntimeError, p1.list_row_sparse_data, row_id)

@with_seed()
def test_paramdict():
    ctx = mx.cpu(1)
    params0 = gluon.ParameterDict('net_')
    params0.get('w0', shape=(10, 10))
    params0.get('w1', shape=(10, 10), stype='row_sparse')
    all_row_ids = mx.nd.arange(0, 10, ctx=ctx)
    # check param names
    assert list(params0.keys()) == ['net_w0', 'net_w1']
    params0.initialize(ctx=ctx)
    trainer0 = mx.gluon.Trainer(params0, 'sgd')
    prev_w0 = params0.get('w0').data(ctx)
    prev_w1 = params0.get('w1').row_sparse_data(all_row_ids)
    # save params
    params0.save('test_paramdict.params')

    # load params
    params1 = gluon.ParameterDict('net_')
    params1.get('w0', shape=(10, 10))
    params1.get('w1', shape=(10, 10), stype='row_sparse')
    params1.load('test_paramdict.params', ctx)
    trainer1 = mx.gluon.Trainer(params1, 'sgd')

    # compare the values before and after save/load
    cur_w0 = params1.get('w0').data(ctx)
    cur_w1 = params1.get('w1').row_sparse_data(all_row_ids)
    mx.test_utils.assert_almost_equal(prev_w0.asnumpy(), cur_w0.asnumpy())
    mx.test_utils.assert_almost_equal(prev_w1.asnumpy(), cur_w1.asnumpy())

    # create a new param dict with dense params, and load from the checkpoint
    # of sparse & dense params
    params2 = gluon.ParameterDict('net_')
    params2.get('w0', shape=(10, 10))
    params2.get('w1', shape=(10, 10))
    params2.load('test_paramdict.params', ctx)

    # compare the values before and after save/load
    cur_w0 = params2.get('w0').data(ctx)
    cur_w1 = params2.get('w1').data(ctx)
    mx.test_utils.assert_almost_equal(prev_w0.asnumpy(), cur_w0.asnumpy())
    mx.test_utils.assert_almost_equal(prev_w1.asnumpy(), cur_w1.asnumpy())


@with_seed()
def test_parameter_row_sparse_data():
    ctx0 = mx.cpu(1)
    ctx1 = mx.cpu(2)
    dim0 = 4
    x = gluon.Parameter('x', shape=(dim0, 2), stype='row_sparse')
    x.initialize(init='xavier', ctx=[ctx0, ctx1])
    trainer = gluon.Trainer([x], 'sgd')
    x_param = x._data[0].copy()
    assert x_param.stype == 'row_sparse'
    row_id_0 = mx.nd.array([0,1], ctx=ctx0)
    retained_0 = x.row_sparse_data(row_id_0)
    retained_target_0 = mx.nd.sparse.retain(x_param, row_id_0.as_in_context(ctx0))
    mx.test_utils.assert_almost_equal(retained_0.asnumpy(), retained_target_0.asnumpy())
    assert retained_0.context == ctx0
    row_id_1 = mx.nd.arange(0, dim0, ctx=ctx1)
    retained_1 = x.row_sparse_data(row_id_1)
    retained_target_1 = x_param
    mx.test_utils.assert_almost_equal(retained_1.asnumpy(), retained_target_1.asnumpy())
    assert retained_1.context == ctx1
    row_id_2 = mx.nd.array([0,1,2])
    retained_2 = x.list_row_sparse_data(row_id_2)
    retained_target_2 = mx.nd.sparse.retain(x_param, row_id_2.as_in_context(ctx0))
    mx.test_utils.assert_almost_equal(retained_2[0].asnumpy(), retained_target_2.asnumpy())


@with_seed()
def test_constant():
    class Test(gluon.HybridBlock):
        def __init__(self, **kwargs):
            super(Test, self).__init__(**kwargs)
            self.value = np.asarray([[1,2], [3,4]])
            self.const = self.params.get_constant('const', self.value)

        def hybrid_forward(self, F, x, const):
            return x + const

    test = Test()
    test.initialize()
    trainer = gluon.Trainer(test.collect_params(), 'sgd',
                            {'learning_rate': 1.0, 'momentum': 0.5})

    with mx.autograd.record():
        x = mx.nd.ones((2,2))
        x.attach_grad()
        y = test(x)
        y.backward()

    trainer.step(1)

    assert (test.const.data().asnumpy() == test.value).all()
    assert (x.grad.asnumpy() == 1).all()


@with_seed()
def test_parameter_sharing():
    class Net(gluon.Block):
        def __init__(self, in_units=0, **kwargs):
            super(Net, self).__init__(**kwargs)
            with self.name_scope():
                self.dense0 = nn.Dense(5, in_units=in_units)
                self.dense1 = nn.Dense(5, in_units=in_units)

        def forward(self, x):
            return self.dense1(self.dense0(x))

    net1 = Net(prefix='net1_', in_units=5)
    net2 = Net(prefix='net2_', params=net1.collect_params())
    net1.collect_params().initialize()
    net2(mx.nd.zeros((3, 5)))

    net1.save_parameters('net1.params')

    net3 = Net(prefix='net3_')
    net3.load_parameters('net1.params', mx.cpu())

    net4 = Net(prefix='net4_')
    net5 = Net(prefix='net5_', in_units=5, params=net4.collect_params())
    net4.collect_params().initialize()
    net5(mx.nd.zeros((3, 5)))

    net4.save_parameters('net4.params')

    net6 = Net(prefix='net6_')
    net6.load_parameters('net4.params', mx.cpu())


@with_seed()
def test_parameter_str():
    class Net(gluon.Block):
        def __init__(self, **kwargs):
            super(Net, self).__init__(**kwargs)
            with self.name_scope():
                self.dense0 = nn.Dense(10, in_units=5, use_bias=False)

    net = Net(prefix='net1_')
    lines = str(net.collect_params()).splitlines()

    assert lines[0] == 'net1_ ('
    assert 'net1_dense0_weight' in lines[1]
    assert '(10, 5)' in lines[1]
    assert 'float32' in lines[1]
    assert lines[2] == ')'


@with_seed()
def test_collect_paramters():
    net = nn.HybridSequential(prefix="test_")
    with net.name_scope():
        net.add(nn.Conv2D(10, 3))
        net.add(nn.Dense(10, activation='relu'))
    assert set(net.collect_params().keys()) == \
        set(['test_conv0_weight', 'test_conv0_bias','test_dense0_weight','test_dense0_bias'])
    assert set(net.collect_params('.*weight').keys()) == \
        set(['test_conv0_weight', 'test_dense0_weight'])
    assert set(net.collect_params('test_conv0_bias|test_dense0_bias').keys()) == \
        set(['test_conv0_bias', 'test_dense0_bias'])

@with_seed()
def test_basic():
    model = nn.Sequential()
    model.add(nn.Dense(128, activation='tanh', in_units=10, flatten=False))
    model.add(nn.Dropout(0.5))
    model.add(nn.Dense(64, activation='tanh', in_units=256),
              nn.Dense(32, in_units=64))
    model.add(nn.Activation('relu'))

    # symbol
    x = mx.sym.var('data')
    y = model(x)
    assert len(y.list_arguments()) == 7

    # ndarray
    model.collect_params().initialize(mx.init.Xavier(magnitude=2.24))
    x = model(mx.nd.zeros((32, 2, 10)))
    assert x.shape == (32, 32)
    x.wait_to_read()

    model.collect_params().setattr('grad_req', 'null')
    assert list(model.collect_params().values())[0]._grad is None
    model.collect_params().setattr('grad_req', 'write')
    assert list(model.collect_params().values())[0]._grad is not None


@with_seed()
def test_dense():
    model = nn.Dense(128, activation='tanh', in_units=10, flatten=False, prefix='test_')
    inputs = mx.sym.Variable('data')
    outputs = model(inputs)
    assert set(model.collect_params().keys()) == set(['test_weight', 'test_bias'])
    assert outputs.list_outputs() == ['test_tanh_fwd_output']
    args, outs, auxs = outputs.infer_shape(data=(2, 3, 10))
    assert outs == [(2, 3, 128)]

    model = nn.Dense(128, activation='relu', in_units=30, flatten=True, prefix='test2_')
    inputs = mx.sym.Variable('data')
    outputs = model(inputs)
    assert set(model.collect_params().keys()) == set(['test2_weight', 'test2_bias'])
    assert outputs.list_outputs() == ['test2_relu_fwd_output']
    args, outs, auxs = outputs.infer_shape(data=(17, 2, 5, 3))
    assert outs == [(17, 128)]


@with_seed()
def test_symbol_block():
    model = nn.HybridSequential()
    model.add(nn.Dense(128, activation='tanh'))
    model.add(nn.Dropout(0.5))
    model.add(nn.Dense(64, activation='tanh'),
              nn.Dense(32, in_units=64))
    model.add(nn.Activation('relu'))

    model.initialize()

    inputs = mx.sym.var('data')
    outputs = model(inputs).get_internals()

    smodel = gluon.SymbolBlock(outputs, inputs, params=model.collect_params())

    assert len(smodel(mx.nd.zeros((16, 10)))) == 14

    out = smodel(mx.sym.var('in'))
    assert len(out) == len(outputs.list_outputs())

    class Net(nn.HybridBlock):
        def __init__(self, model):
            super(Net, self).__init__()
            self.model = model

        def hybrid_forward(self, F, x):
            out = self.model(x)
            return F.add_n(*[i.sum() for i in out])

    net = Net(smodel)
    net.hybridize()
    assert isinstance(net(mx.nd.zeros((16, 10))), mx.nd.NDArray)

    inputs = mx.sym.var('data')
    outputs = model(inputs)
    smodel = gluon.SymbolBlock(outputs, inputs, params=model.collect_params())
    net = Net(smodel)
    net.hybridize()
    assert isinstance(net(mx.nd.zeros((16, 10))), mx.nd.NDArray)

    # Test case to verify if initializing the SymbolBlock from a model with params
    # other than fp32 param dtype.

    # 1. Load a resnet model, cast it to fp64 and export
    tmp = tempfile.mkdtemp()
    tmpfile = os.path.join(tmp, 'resnet34_fp64')
    ctx = mx.cpu(0)

    net_fp32 = mx.gluon.model_zoo.vision.resnet34_v2(pretrained=True, ctx=ctx, root=tmp)
    net_fp32.cast('float64')
    net_fp32.hybridize()
    data = mx.nd.zeros((1,3,224,224), dtype='float64', ctx=ctx)
    net_fp32.forward(data)
    net_fp32.export(tmpfile, 0)

    # 2. Load the saved model and verify if all the params are loaded correctly.
    # and choose one of the param to verify the type if fp64.
    sm = mx.sym.load(tmpfile + '-symbol.json')
    inputs = mx.sym.var('data', dtype='float64')
    net_fp64 = mx.gluon.SymbolBlock(sm, inputs)
    net_fp64.collect_params().load(tmpfile + '-0000.params', ctx=ctx)
    # 3. Get a conv layer's weight parameter name. Conv layer's weight param is
    # expected to be of dtype casted, fp64.
    for param_name in net_fp64.params.keys():
        if 'conv' in param_name and 'weight' in param_name:
            break
    assert np.dtype(net_fp64.params[param_name].dtype) == np.dtype(np.float64)

    # Cast the symbol block to FP32 and try to forward a FP32 data.
    # This will verify SymbolBlock.cast() functionality.
    net_fp64.cast('float32')
    fp32_data = mx.nd.zeros((1,3,224,224), dtype='float32', ctx=ctx)
    prediction = net_fp64.forward(fp32_data)
    assert np.dtype(prediction.dtype) == np.dtype(np.float32)

@with_seed()
@raises(AssertionError)
def test_sparse_symbol_block():
    data = mx.sym.var('data')
    weight = mx.sym.var('weight', stype='row_sparse')
    bias = mx.sym.var('bias')
    out = mx.sym.broadcast_add(mx.sym.dot(data, weight), bias)
    # an exception is expected when creating a SparseBlock w/ sparse param
    net = gluon.SymbolBlock(out, data)

@with_seed()
@raises(RuntimeError)
def test_sparse_hybrid_block():
    params = gluon.ParameterDict('net_')
    params.get('weight', shape=(5,5), stype='row_sparse', dtype='float32')
    params.get('bias', shape=(5), dtype='float32')
    net = gluon.nn.Dense(5, params=params)
    net.initialize()
    x = mx.nd.ones((2,5))
    # an exception is expected when forwarding a HybridBlock w/ sparse param
    y = net(x)

@with_seed()
def check_layer_forward(layer, dshape):
    print("checking layer {}\nshape: {}.".format(layer, dshape))
    layer.collect_params().initialize()
    x = mx.nd.ones(shape=dshape)
    x.attach_grad()
    with mx.autograd.record():
        out = layer(x)
    out.backward()

    np_out = out.asnumpy()
    np_dx = x.grad.asnumpy()

    layer.hybridize()

    x = mx.nd.ones(shape=dshape)
    x.attach_grad()
    with mx.autograd.record():
        out = layer(x)
    out.backward()

    mx.test_utils.assert_almost_equal(np_out, out.asnumpy(), rtol=1e-5, atol=1e-6)
    mx.test_utils.assert_almost_equal(np_dx, x.grad.asnumpy(), rtol=1e-5, atol=1e-6)

@unittest.skip("Flaky test: https://github.com/apache/incubator-mxnet/issues/11506")
@with_seed()
def test_conv():
    layers1d = [
        nn.Conv1D(16, 3, in_channels=4),
        nn.Conv1D(16, 3, groups=2, in_channels=4),
        nn.Conv1D(16, 3, strides=3, groups=2, in_channels=4),
        ]
    for layer in layers1d:
        check_layer_forward(layer, (1, 4, 10))


    layers2d = [
        nn.Conv2D(16, (3, 4), in_channels=4),
        nn.Conv2D(16, (5, 4), in_channels=4),
        nn.Conv2D(16, (3, 4), groups=2, in_channels=4),
        nn.Conv2D(16, (3, 4), strides=4, in_channels=4),
        nn.Conv2D(16, (3, 4), dilation=4, in_channels=4),
        nn.Conv2D(16, (3, 4), padding=4, in_channels=4),
        ]
    for layer in layers2d:
        check_layer_forward(layer, (1, 4, 20, 20))


    layers3d = [
        nn.Conv3D(16, (1, 8, 4), in_channels=4, activation='relu'),
        nn.Conv3D(16, (5, 4, 3), in_channels=4),
        nn.Conv3D(16, (3, 3, 3), groups=2, in_channels=4),
        nn.Conv3D(16, 4, strides=4, in_channels=4),
        nn.Conv3D(16, (3, 3, 3), padding=4, in_channels=4),
        ]
    for layer in layers3d:
        check_layer_forward(layer, (1, 4, 10, 10, 10))


    layer = nn.Conv2D(16, (3, 3), layout='NHWC', in_channels=4)
    # check_layer_forward(layer, (1, 10, 10, 4))

    layer = nn.Conv3D(16, (3, 3, 3), layout='NDHWC', in_channels=4)
    # check_layer_forward(layer, (1, 10, 10, 10, 4))


@with_seed()
def test_deconv():
    # layers1d = [
    #     nn.Conv1DTranspose(16, 3, in_channels=4),
    #     nn.Conv1DTranspose(16, 3, groups=2, in_channels=4),
    #     nn.Conv1DTranspose(16, 3, strides=3, groups=2, in_channels=4),
    #     ]
    # for layer in layers1d:
    #     check_layer_forward(layer, (1, 4, 10))


    layers2d = [
        nn.Conv2DTranspose(16, (3, 4), in_channels=4),
        nn.Conv2DTranspose(16, (5, 4), in_channels=4),
        nn.Conv2DTranspose(16, (3, 4), groups=2, in_channels=4),
        nn.Conv2DTranspose(16, (3, 4), strides=4, in_channels=4),
        nn.Conv2DTranspose(16, (3, 4), dilation=4, in_channels=4),
    #   nn.Conv2DTranspose(16, (3, 4), padding=4, in_channels=4),
        nn.Conv2DTranspose(16, (3, 4), strides=4, output_padding=3, in_channels=4),
        ]
    for layer in layers2d:
        check_layer_forward(layer, (1, 4, 20, 20))


    # layers3d = [
    #     nn.Conv3DTranspose(16, (1, 8, 4), in_channels=4),
    #     nn.Conv3DTranspose(16, (5, 4, 3), in_channels=4),
    #     nn.Conv3DTranspose(16, (3, 3, 3), groups=2, in_channels=4),
    #     nn.Conv3DTranspose(16, 4, strides=4, in_channels=4),
    #     nn.Conv3DTranspose(16, (3, 3, 3), padding=4, in_channels=4),
    #     ]
    # for layer in layers3d:
    #     check_layer_forward(layer, (1, 4, 10, 10, 10))
    #
    #
    # layer = nn.Conv2DTranspose(16, (3, 3), layout='NHWC', in_channels=4)
    # # check_layer_forward(layer, (1, 10, 10, 4))
    #
    # layer = nn.Conv3DTranspose(16, (3, 3, 3), layout='NDHWC', in_channels=4)
    # # check_layer_forward(layer, (1, 10, 10, 10, 4))


@with_seed()
def test_pool():
    layers1d = [
        nn.MaxPool1D(),
        nn.MaxPool1D(3),
        nn.MaxPool1D(3, 2),
        nn.AvgPool1D(),
        nn.AvgPool1D(count_include_pad=False),
        nn.GlobalAvgPool1D(),
        ]
    for layer in layers1d:
        check_layer_forward(layer, (1, 2, 10))


    layers2d = [
        nn.MaxPool2D(),
        nn.MaxPool2D((3, 3)),
        nn.MaxPool2D(3, 2),
        nn.AvgPool2D(),
        nn.AvgPool2D(count_include_pad=False),
        nn.GlobalAvgPool2D(),
        ]
    for layer in layers2d:
        check_layer_forward(layer, (1, 2, 10, 10))

    layers3d = [
        nn.MaxPool3D(),
        nn.MaxPool3D((3, 3, 3)),
        nn.MaxPool3D(3, 2),
        nn.AvgPool3D(),
        nn.AvgPool3D(count_include_pad=False),
        nn.GlobalAvgPool3D(),
        ]
    for layer in layers3d:
        check_layer_forward(layer, (1, 2, 10, 10, 10))

    # test ceil_mode
    x = mx.nd.zeros((2, 2, 10, 10))

    layer = nn.MaxPool2D(3, ceil_mode=False)
    layer.collect_params().initialize()
    assert (layer(x).shape==(2, 2, 3, 3))

    layer = nn.MaxPool2D(3, ceil_mode=True)
    layer.collect_params().initialize()
    assert (layer(x).shape==(2, 2, 4, 4))


@with_seed()
def test_batchnorm():
    layer = nn.BatchNorm(in_channels=10)
    check_layer_forward(layer, (2, 10, 10, 10))


@with_seed()
def test_instancenorm():
    layer = nn.InstanceNorm(in_channels=10)
    check_layer_forward(layer, (2, 10, 10, 10))

@with_seed()
def test_layernorm():
    layer = nn.LayerNorm(in_channels=10)
    check_layer_forward(layer, (2, 10, 10, 10))


@with_seed()
def test_reflectionpad():
    layer = nn.ReflectionPad2D(3)
    check_layer_forward(layer, (2, 3, 24, 24))


@with_seed()
def test_reshape():
    x = mx.nd.ones((2, 4, 10, 10))
    layer = nn.Conv2D(10, 2, in_channels=4)
    layer.collect_params().initialize()
    with mx.autograd.record():
        x = layer(x)
        x = x.reshape((-1,))
        x = x + 10
    x.backward()


@with_seed()
def test_slice():
    x = mx.nd.ones((5, 4, 10, 10))
    layer = nn.Conv2D(10, 2, in_channels=4)
    layer.collect_params().initialize()
    with mx.autograd.record():
        x = layer(x)
        x = x[1:3]
        x = x + 10
    x.backward()


@with_seed()
def test_at():
    x = mx.nd.ones((5, 4, 10, 10))
    layer = nn.Conv2D(10, 2, in_channels=4)
    layer.collect_params().initialize()
    with mx.autograd.record():
        x = layer(x)
        x = x[1]
        x = x + 10
    x.backward()


@with_seed()
def test_deferred_init():
    x = mx.nd.ones((5, 4, 10, 10))
    layer = nn.Conv2D(10, 2)
    layer.collect_params().initialize()
    layer(x)


def check_split_data(x, num_slice, batch_axis, **kwargs):
    res = gluon.utils.split_data(x, num_slice, batch_axis, **kwargs)
    assert len(res) == num_slice
    mx.test_utils.assert_almost_equal(mx.nd.concat(*res, dim=batch_axis).asnumpy(),
                                      x.asnumpy())


@with_seed()
def test_split_data():
    x = mx.nd.random.uniform(shape=(128, 33, 64))

    check_split_data(x, 8, 0)
    check_split_data(x, 3, 1)
    check_split_data(x, 4, 1, even_split=False)
    check_split_data(x, 15, 1, even_split=False)
    try:
        check_split_data(x, 4, 1)
    except ValueError:
        return
    assert False, "Should have failed"


@with_seed()
def test_flatten():
    flatten = nn.Flatten()
    x = mx.nd.zeros((3,4,5,6))
    assert flatten(x).shape == (3, 4*5*6)
    x = mx.nd.zeros((3,6))
    assert flatten(x).shape == (3, 6)
    x = mx.nd.zeros((3,))
    assert flatten(x).shape == (3, 1)

@with_seed()
def test_block_attr_hidden():
    b = gluon.Block()

    # regular attributes can change types
    b.a = None
    b.a = 1


@raises(TypeError)
@with_seed()
def test_block_attr_block():
    b = gluon.Block()

    # regular variables can't change types
    b.b = gluon.Block()
    b.b = (2,)


@raises(TypeError)
@with_seed()
def test_block_attr_param():
    b = gluon.Block()

    # regular variables can't change types
    b.b = gluon.Parameter()
    b.b = (2,)


@with_seed()
def test_block_attr_regular():
    b = gluon.Block()

    # set block attribute also sets _children
    b.c = gluon.Block()
    c2 = gluon.Block()
    b.c = c2
    assert b.c is c2 and list(b._children.values())[0] is c2


@with_seed()
def test_block_attr_list_of_block():
    class Model1(gluon.Block):
        def __init__(self, **kwargs):
            super(Model1, self).__init__(**kwargs)
            with self.name_scope():
                self.layers = [nn.Dense(i * 10) for i in range(6)]

    class Model2(gluon.Block):
        def __init__(self, **kwargs):
            super(Model2, self).__init__(**kwargs)
            with self.name_scope():
                self.layers = dict()
                self.layers['a'] = [nn.Dense(10), nn.Dense(10)]

    class Model3(gluon.Block):
        def __init__(self, **kwargs):
            super(Model3, self).__init__(**kwargs)
            with self.name_scope():
                self.layers = nn.Sequential()
                self.layers.add(*[nn.Dense(i * 10) for i in range(6)])

    class Model4(gluon.Block):
        def __init__(self, **kwargs):
            super(Model4, self).__init__(**kwargs)
            with self.name_scope():
                self.data = {'a': '4', 'b': 123}

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        model = Model1()
        model.collect_params()
        assert len(w) > 0
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        model = Model2()
        model.collect_params()
        assert len(w) > 0
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        model = Model3()
        model.collect_params()
        assert len(w) == 0
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        model = Model4()
        model.collect_params()
        assert len(w) == 0

def check_sequential(net):
    dense1 = gluon.nn.Dense(10)
    net.add(dense1)
    dense2 = gluon.nn.Dense(10)
    net.add(dense2)
    dense3 = gluon.nn.Dense(10)
    net.add(dense3)

    assert net[1] is dense2
    assert net[-1] is dense3
    slc = net[1:3]
    assert len(slc) == 2 and slc[0] is dense2 and slc[1] is dense3
    assert isinstance(slc, type(net))

@with_seed()
def test_sequential():
    check_sequential(gluon.nn.Sequential())
    check_sequential(gluon.nn.HybridSequential())

@with_seed()
def test_sequential_warning():
    with warnings.catch_warnings(record=True) as w:
        # The following line permits the test to pass if run multiple times
        warnings.simplefilter('always')
        b = gluon.nn.Sequential()
        b.add(gluon.nn.Dense(20))
        b.hybridize()
        assert len(w) == 1


@with_seed()
def test_global_norm_clip():
    stypes = ['default', 'row_sparse']
    def check_global_norm_clip(stype):
        x1 = mx.nd.ones((3,3)).tostype(stype)
        x2 = mx.nd.ones((4,4)).tostype(stype)
        norm = gluon.utils.clip_global_norm([x1, x2], 1.0)
        assert norm == 5.0
        assert_almost_equal(x1.asnumpy(), np.ones((3,3))/5)
        assert_almost_equal(x2.asnumpy(), np.ones((4,4))/5)

        x3 = mx.nd.array([1.0, 2.0, float('nan')]).tostype(stype)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            gluon.utils.clip_global_norm([x1, x3], 2.0)
            assert len(w) == 1

    for stype in stypes:
        check_global_norm_clip(stype)

@with_seed()
def test_embedding():
    def check_embedding(sparse_grad):
        layer = gluon.nn.Embedding(10, 100, sparse_grad=sparse_grad)
        layer.initialize()
        x = mx.nd.array([3,4,2,0,1])
        with mx.autograd.record():
            y = layer(x)
            y.backward()
        assert (layer.weight.grad().asnumpy()[:5] == 1).all()
        assert (layer.weight.grad().asnumpy()[5:] == 0).all()

    def check_embedding_large_input(sparse_grad):
        embedding = mx.gluon.nn.Embedding(10, 1, sparse_grad=True)
        embedding.initialize()
        embedding.hybridize()
        shape = (20481,)
        with mx.autograd.record():
            emb_in = embedding(mx.nd.ones(shape))
            loss = emb_in.sum()
        loss.backward()
        assert embedding.weight.grad().data.sum().asscalar() == 20481

    check_embedding(True)
    check_embedding(False)
    check_embedding_large_input(True)
    check_embedding_large_input(False)

@unittest.skip("Flaky test: https://github.com/apache/incubator-mxnet/issues/11616")
@with_seed()
def test_export():
    ctx = mx.context.current_context()
    model = gluon.model_zoo.vision.resnet18_v1(
        prefix='resnet', ctx=ctx, pretrained=True)
    model.hybridize()
    data = mx.nd.random.normal(shape=(1, 3, 32, 32))
    out = model(data)

    model.export('gluon')

    module = mx.mod.Module.load('gluon', 0, label_names=None, context=ctx)
    module.bind(data_shapes=[('data', data.shape)])
    module.forward(mx.io.DataBatch([data], None), is_train=False)
    mod_out, = module.get_outputs()

    assert_almost_equal(out.asnumpy(), mod_out.asnumpy())

    model2 = gluon.model_zoo.vision.resnet18_v1(prefix='resnet', ctx=ctx)
    model2.collect_params().load('gluon-0000.params', ctx)
    out2 = model2(data)

    assert_almost_equal(out.asnumpy(), out2.asnumpy())

@with_seed()
def test_import():
    ctx = mx.context.current_context()
    net1 = gluon.model_zoo.vision.resnet18_v1(
        prefix='resnet', ctx=ctx, pretrained=True)
    net1.hybridize()
    data = mx.nd.random.normal(shape=(1, 3, 32, 32))
    out1 = net1(data)

    net1.export('net1', epoch=1)

    net2 = gluon.SymbolBlock.imports(
        'net1-symbol.json', ['data'], 'net1-0001.params', ctx)
    out2 = net2(data)

    assert_almost_equal(out1.asnumpy(), out2.asnumpy())

@with_seed()
def test_hybrid_stale_cache():
    net = mx.gluon.nn.HybridSequential()
    with net.name_scope():
        net.add(mx.gluon.nn.Dense(10, weight_initializer='zeros', bias_initializer='ones', flatten=False))

    net.hybridize()
    net.initialize()
    net(mx.nd.ones((2,3,5)))

    net.add(mx.gluon.nn.Flatten())
    assert net(mx.nd.ones((2,3,5))).shape == (2, 30)

    net = mx.gluon.nn.HybridSequential()
    with net.name_scope():
        net.fc1 = mx.gluon.nn.Dense(10, weight_initializer='zeros',
                                    bias_initializer='ones', flatten=False)
        net.fc2 = mx.gluon.nn.Dense(10, weight_initializer='zeros',
                                    bias_initializer='ones', flatten=False)
    net.hybridize()
    net.initialize()
    net(mx.nd.ones((2,3,5)))

    net.fc2 = mx.gluon.nn.Dense(10, weight_initializer='zeros',
                                bias_initializer='ones', flatten=True)
    net.initialize()
    assert net(mx.nd.ones((2,3,5))).shape == (2, 10)


@with_seed()
def test_lambda():
    net1 = mx.gluon.nn.HybridSequential()
    net1.add(nn.Activation('tanh'),
             nn.LeakyReLU(0.1))

    net2 = mx.gluon.nn.HybridSequential()
    op3 = lambda F, x, *args: F.LeakyReLU(x, *args, slope=0.1)
    net2.add(nn.HybridLambda('tanh'),
             nn.HybridLambda(op3))

    op4 = lambda x: mx.nd.LeakyReLU(x, slope=0.1)
    net3 = mx.gluon.nn.Sequential()
    net3.add(nn.Lambda('tanh'),
             nn.Lambda(op4))

    input_data = mx.nd.random.uniform(shape=(2, 3, 5, 7))
    out1, out2, out3 = net1(input_data), net2(input_data), net3(input_data)
    assert_almost_equal(out1.asnumpy(), out2.asnumpy(), rtol=1e-3, atol=1e-3)
    assert_almost_equal(out1.asnumpy(), out3.asnumpy(), rtol=1e-3, atol=1e-3)


@with_seed()
def test_fill_shape_deferred():
    net = nn.HybridSequential()
    with net.name_scope():
        net.add(nn.Conv2D(64, kernel_size=2, padding=1),
                nn.BatchNorm(),
                nn.Dense(10))
    net.hybridize()
    net.initialize()
    net(mx.nd.ones((2,3,5,7)))
    assert net[0].weight.shape[1] == 3, net[0].weight.shape[1]
    assert net[1].gamma.shape[0] == 64, net[1].gamma.shape[0]
    assert net[2].weight.shape[1] == 3072, net[2].weight.shape[1]


@with_seed()
def test_dtype():
    net = mx.gluon.model_zoo.vision.resnet18_v1()
    net.initialize()
    net.cast('float64')
    with mx.autograd.record():
        y = net(mx.nd.ones((16, 3, 32, 32), dtype='float64'))
        y.backward()

    net = mx.gluon.model_zoo.vision.resnet18_v1()
    net.initialize()
    net.hybridize()
    net(mx.nd.ones((16, 3, 32, 32), dtype='float32'))

    net.cast('float64')
    net(mx.nd.ones((16, 3, 32, 32), dtype='float64'))

    mx.nd.waitall()

    class Net(gluon.Block):
        def __init__(self, in_dim, output_dim):
            super(Net, self).__init__()
            with self.name_scope():
                self.embed = gluon.nn.Embedding(input_dim=in_dim, output_dim=output_dim,dtype=np.float64)
                self.dense = gluon.nn.Dense(2, dtype=np.float64)

        def forward(self, x):
            e = self.embed(x)
            assert(e.dtype == np.float64)
            y = self.dense(e)
            assert(y.dtype == np.float64)
            return y

    net = Net(5, 10)
    net.initialize()
    out = net(mx.nd.ones((3,), dtype=np.float64))
    mx.nd.waitall()

@with_seed()
def test_fill_shape_load():
    ctx = mx.context.current_context()
    net1 = nn.HybridSequential()
    with net1.name_scope():
        net1.add(nn.Conv2D(64, kernel_size=2, padding=1),
                 nn.BatchNorm(),
                 nn.Dense(10))
    net1.hybridize()
    net1.initialize(ctx=ctx)
    net1(mx.nd.ones((2,3,5,7), ctx))
    net1.save_parameters('net_fill.params')

    net2 = nn.HybridSequential()
    with net2.name_scope():
        net2.add(nn.Conv2D(64, kernel_size=2, padding=1),
                 nn.BatchNorm(),
                 nn.Dense(10))
    net2.hybridize()
    net2.initialize()
    net2.load_parameters('net_fill.params', ctx)
    assert net2[0].weight.shape[1] == 3, net2[0].weight.shape[1]
    assert net2[1].gamma.shape[0] == 64, net2[1].gamma.shape[0]
    assert net2[2].weight.shape[1] == 3072, net2[2].weight.shape[1]


@with_seed()
def test_inline():
    net = mx.gluon.nn.HybridSequential()
    with net.name_scope():
        net.add(mx.gluon.nn.Dense(10))
        net.add(mx.gluon.nn.Dense(10))
        net.add(mx.gluon.nn.Dense(10))

    net.initialize()
    net.hybridize(inline_limit=3)
    with mx.autograd.record():
        y = net(mx.nd.zeros((1,10)))

    len_1 = len(json.loads(mx.autograd.get_symbol(y).tojson())['nodes'])
    y.backward()

    net.hybridize(inline_limit=0)
    with mx.autograd.record():
        y = net(mx.nd.zeros((1,10)))

    len_2 = len(json.loads(mx.autograd.get_symbol(y).tojson())['nodes'])
    y.backward()

    assert len_1 == len_2 + 2


@with_seed()
def test_activations():
    point_to_validate = mx.nd.array([-0.1, 0.1] * 3)

    swish = mx.gluon.nn.Swish()
    def swish_test(x):
        return x * mx.nd.sigmoid(x)

    for test_point, ref_point in zip(swish_test(point_to_validate), swish(point_to_validate)):
        assert test_point == ref_point

    elu = mx.gluon.nn.ELU()
    def elu_test(x):
        def elu(x):
            return 1.0 * (mx.nd.exp(x) - 1) if x < 0 else x
        return [elu(x_i) for x_i in x]

    for test_point, ref_point in zip(elu_test(point_to_validate), elu(point_to_validate)):
        assert test_point == ref_point

    selu = mx.gluon.nn.SELU()
    def selu_test(x):
        def selu(x):
            scale, alpha = 1.0507009873554804934193349852946, 1.6732632423543772848170429916717
            return scale * x if x >= 0 else alpha * mx.nd.exp(x) - alpha
        return [selu(x_i) for x_i in x]

    for test_point, ref_point in zip(selu(point_to_validate), selu(point_to_validate)):
        assert test_point == ref_point

    prelu = mx.gluon.nn.PReLU()
    prelu.initialize()
    x = point_to_validate.reshape((1, 3, 2))
    assert_almost_equal(prelu(x).asnumpy(), mx.nd.where(x >= 0, x, 0.25 * x).asnumpy())

@with_seed()
def test_dropout():
    def get_slice(x, axis, idx):
        ix = ()
        for i in range(x.ndim):
            if i == axis:
                ix += (idx,)
            else:
                ix += (slice(None, None, None),)
        return x[ix]

    def check_dropout_axes(ratio, shape, axes):
        compactshape = list(shape)
        for axis in axes:
            compactshape[axis] = 1
        compactx = mx.random.uniform(shape=tuple(compactshape))
        broadcastx = compactx.broadcast_to(shape)
        dropouty = mx.gluon.nn.Dropout(rate=ratio, axes=axes)(broadcastx)
        for axis in axes:
            target = get_slice(dropouty, axis, 0).asnumpy()
            for i in range(1, shape[axis]):
                assert(get_slice(dropouty, axis, i).asnumpy() == target).all()

    nshape = (10, 10, 10, 10)
    with mx.autograd.train_mode():
        check_dropout_axes(0.25, nshape, axes = (0,))
        check_dropout_axes(0.25, nshape, axes = (1,))
        check_dropout_axes(0.25, nshape, axes = (2,))
        check_dropout_axes(0.25, nshape, axes = (3,))
        check_dropout_axes(0.25, nshape, axes = (0, 1))
        check_dropout_axes(0.25, nshape, axes = (0, 2))
        check_dropout_axes(0.25, nshape, axes = (0, 3))
        check_dropout_axes(0.25, nshape, axes = (1, 2))
        check_dropout_axes(0.25, nshape, axes = (1, 3))
        check_dropout_axes(0.25, nshape, axes = (2, 3))
        check_dropout_axes(0.25, nshape, axes = (0, 1, 2))
        check_dropout_axes(0.25, nshape, axes = (0, 2, 3))
        check_dropout_axes(0.25, nshape, axes = (1, 2, 3))

@with_seed()
def test_req():
    data = mx.nd.random.uniform(shape=(1,3,224,224))
    label = mx.nd.random.uniform(shape=(1))
    label[:] = 1
    loss = gluon.loss.SoftmaxCrossEntropyLoss()

    net = nn.HybridSequential()
    net1 = nn.HybridSequential()
    net1.add(nn.Dense(4))
    net2 = nn.HybridSequential()
    net2.add(nn.Dense(3))
    net2.add(nn.Dense(2))
    net.add(net1)
    net.add(net2)
    net.initialize()

    net.hybridize()

    for v in net.collect_params().values():
        v.grad_req = 'add'

    net.collect_params().zero_grad()
    with mx.autograd.record():
        pred = net(data)
        l = loss(pred, label)
        l.backward()
        grad = net[0][0].weight.grad().mean().asnumpy()
        # run twice to check req = add
        pred = net(data)
        l = loss(pred, label)
        l.backward()

    grad_double = net[0][0].weight.grad().mean().asnumpy()
    assert_almost_equal(grad * 2, grad_double)


@with_seed()
def test_save_load():
    net = mx.gluon.model_zoo.vision.get_resnet(1, 18, pretrained=True)
    net.save_parameters('test_save_load.params')

    net = mx.gluon.model_zoo.vision.get_resnet(1, 18)
    net.output = mx.gluon.nn.Dense(1000)

    net.load_parameters('test_save_load.params')

    class Network(gluon.Block):
        def __init__(self, **kwargs):
            super(Network, self).__init__(**kwargs)
            with self.name_scope():
                self.encoders = gluon.nn.Sequential()
                with self.encoders.name_scope():
                    for _ in range(2):
                        lstm = mx.gluon.rnn.LSTM(200, 1, bidirectional=True)
                        self.encoders.add(lstm)

        def forward(self, x):
            for i in range(2):
                x = self.encoders[i](x)
            return x
    net = Network()
    net.initialize(mx.init.Xavier(), ctx=mx.cpu())
    net.hybridize()
    x = np.random.rand(32, 10, 10)
    x = mx.nd.array(x).as_in_context(mx.cpu())
    net(x)
    net.save_parameters('tmp.params')
    net2 = Network()
    net2.load_parameters('tmp.params')

@with_seed()
def test_symbol_block_save_load():
    class Net(gluon.HybridBlock):
        def __init__(self):
            super(Net, self).__init__()
            with self.name_scope():
                backbone = gluon.model_zoo.vision.resnet18_v1()
                data = mx.sym.var('data')
                featnames = ['stage1_activation0', 'stage2_activation0', 'stage3_activation0']
                out_names = ['_'.join([backbone.name, featname, 'output']) for featname in featnames]
                internals = backbone(data).get_internals()
                outs = [internals[out_name] for out_name in out_names]
                self.backbone = gluon.SymbolBlock(outs, data, params=backbone.collect_params())
                self.body = nn.Conv2D(3, 1)

        def hybrid_forward(self, F, x):
            x = self.body(x)
            return self.backbone(x)

    net1 = Net()
    net1.initialize(mx.init.Normal())
    net1.hybridize()
    net1(mx.nd.random.normal(shape=(1, 3, 32, 32)))
    net1.save_parameters('./test_symbol_block_save_load.params')

    net2 = Net()
    net2.load_parameters('./test_symbol_block_save_load.params', ctx=mx.cpu())


@with_seed()
def test_hybrid_multi_context():
    net = mx.gluon.model_zoo.vision.get_resnet(1, 18)
    net.initialize(ctx=[mx.cpu(0), mx.cpu(1)])
    net.hybridize()
    net(mx.nd.zeros((1, 3, 32, 32), ctx=mx.cpu(0))).asnumpy()

@with_seed()
def test_zero_grad():
    data = mx.nd.random.uniform(shape=(3,3))
    net = nn.Embedding(3, 4, sparse_grad=True, prefix='test_zero_grad_')
    net.initialize()
    with mx.autograd.record():
        l = net(data)
        l.backward()
    net.collect_params().zero_grad()
    grad = net.collect_params()['test_zero_grad_weight'].grad()
    assert_almost_equal(grad.asnumpy(), grad.asnumpy() * 0)

def check_hybrid_static_memory(**kwargs):
    x = mx.nd.random.uniform(shape=(2, 3, 32, 32))
    x.attach_grad()

    net1 = gluon.model_zoo.vision.get_resnet(
        1, 18, pretrained=True, prefix='net_', ctx=mx.context.current_context())
    net2 = gluon.model_zoo.vision.get_resnet(
        1, 18, pretrained=True, prefix='net_', ctx=mx.context.current_context())
    net2.hybridize(**kwargs)
    net1(x)
    net2(x)

    def test(net, x):
        with mx.autograd.record():
            y = net(x) + net(x)
            y.backward()

        grads = {k: v.grad() for k, v in net.collect_params().items() if v.grad_req != 'null'}

        return y, grads

    y1, grads1 = test(net1, x)
    y2, grads2 = test(net2, x)

    assert_almost_equal(y1.asnumpy(), y2.asnumpy(), rtol=1e-3, atol=1e-5)
    for key in grads1:
        assert_almost_equal(grads1[key].asnumpy(), grads2[key].asnumpy(), rtol=1e-3, atol=1e-5)

@with_seed()
def test_hybrid_static_memory():
    check_hybrid_static_memory()
    check_hybrid_static_memory(static_alloc=True)
    check_hybrid_static_memory(static_alloc=True, static_shape=True)

def check_hybrid_static_memory_switching(**kwargs):
    net = gluon.model_zoo.vision.get_resnet(
        1, 18, pretrained=True, ctx=mx.context.current_context())
    net.hybridize(**kwargs)

    x = mx.nd.random.uniform(shape=(4, 3, 32, 32))
    net(x)
    with mx.autograd.record():
        y = net(x)
        y.backward()
    x = mx.nd.random.uniform(shape=(2, 3, 32, 32))
    net(x)
    with mx.autograd.record():
        y = net(x)
        y.backward()
    mx.nd.waitall()

@with_seed()
def test_hybrid_static_memory_switching():
    check_hybrid_static_memory_switching()
    check_hybrid_static_memory_switching(static_alloc=True)
    check_hybrid_static_memory_switching(static_alloc=True, static_shape=True)

@with_seed()
def test_hook():
    global hook_call_count
    hook_call_count = 0
    global pre_hook_call_count
    pre_hook_call_count = 0

    def call_hook(block, x, y):
        global hook_call_count
        hook_call_count += 1

    def call_pre_hook(block, x):
        global pre_hook_call_count
        pre_hook_call_count += 1

    block = nn.Dense(10)
    block.initialize()
    handle = block.register_forward_hook(call_hook)
    pre_handle = block.register_forward_pre_hook(call_pre_hook)
    block(mx.nd.ones((3, 5)))

    assert hook_call_count == 1
    assert pre_hook_call_count == 1

    handle.detach()
    block(mx.nd.ones((3, 5)))

    assert hook_call_count == 1
    assert pre_hook_call_count == 2

    pre_handle.detach()
    block(mx.nd.ones((3, 5)))
    assert hook_call_count == 1
    assert pre_hook_call_count == 2


@with_seed()
def test_apply():
    global called_blocks
    called_blocks = []

    def record_name(block):
        global called_blocks
        called_blocks.append(block.name)

    block = nn.HybridSequential(prefix='test_')
    with block.name_scope():
        block.add(nn.Dense(10))
        block.add(nn.Dropout(0.5))
    block.apply(record_name)

    assert called_blocks == ['test_dense0', 'test_dropout0', 'test']


@with_seed()
@assert_raises_cudnn_not_satisfied(min_version='5.1.10')
def test_summary():
    net = gluon.model_zoo.vision.resnet50_v1()
    net.initialize()
    net.summary(mx.nd.ones((32, 3, 224, 224)))

    net2 = nn.Sequential()
    with net2.name_scope():
        net2.add(nn.Embedding(40, 30))
        net2.add(gluon.rnn.LSTM(30))
        net2.add(nn.Dense(40, flatten=False, params=net2[0].params))
    net2.initialize()
    net2.summary(mx.nd.ones((80, 32)))

    net3 = gluon.rnn.LSTM(30)
    net3.initialize()
    begin_state = net3.begin_state(32)
    net3.summary(mx.nd.ones((80, 32, 5)), begin_state)

    net.hybridize()
    assert_raises(AssertionError, net.summary, mx.nd.ones((32, 3, 224, 224)))


@with_seed()
def test_legacy_save_params():
    net = gluon.nn.HybridSequential(prefix='')
    with net.name_scope():
        net.add(gluon.nn.Conv2D(10, (3, 3)))
        net.add(gluon.nn.Dense(50))
    net.initialize()
    net(mx.nd.ones((1,1,50,50)))
    a = net(mx.sym.var('data'))
    a.save('test.json')
    net.save_params('test.params')
    model = gluon.nn.SymbolBlock(outputs=mx.sym.load_json(open('test.json', 'r').read()),
                                     inputs=mx.sym.var('data'))
    model.load_params('test.params', ctx=mx.cpu())


@with_seed()
def test_sparse_hybrid_block_grad():
    class Embedding(mx.gluon.HybridBlock):
        def __init__(self, num_tokens, embedding_size):
            super(Embedding, self).__init__()
            self.num_tokens = num_tokens

            with self.name_scope():
                self.embedding = mx.gluon.nn.Embedding(
                    num_tokens, embedding_size, sparse_grad=True)

        def hybrid_forward(self, F, words):
            emb = self.embedding(words)
            return emb + F.ones_like(emb)

    embedding = Embedding(20, 3)
    embedding.initialize()
    embedding.hybridize()

    with mx.autograd.record():
        emb0 = embedding(mx.nd.arange(10)).sum()
        emb1 = embedding(mx.nd.arange(10)).sum()
        loss = emb0 + emb1
    loss.backward()
    grad = embedding.embedding.weight.grad().asnumpy()
    assert (grad[:10] == 2).all()
    assert (grad[10:] == 0).all()

@with_seed()
def test_sparse_hybrid_block():
    class Linear(mx.gluon.HybridBlock):
        def __init__(self, units):
            super(Linear, self).__init__()
            with self.name_scope():
                self.w = self.params.get('w', shape=(units, units))

        def hybrid_forward(self, F, x, w):
            return F.dot(x, w)

    class SparseBlock(mx.gluon.HybridBlock):
        def __init__(self, units):
            super(SparseBlock, self).__init__()
            with self.name_scope():
                self.net = Linear(units)

        def hybrid_forward(self, F, x):
            return self.net(x) * x

    block = SparseBlock(2)
    block.initialize()
    block.hybridize()
    x = mx.nd.ones((2,2)).tostype('csr')
    with mx.autograd.record():
        z = block(x) + block(x)
    z.backward()
    assert (block.net.w.grad().asnumpy() == 4).all()

def test_hybrid_static_memory_recording():
    net = gluon.model_zoo.vision.get_resnet(
        1, 18, pretrained=True, ctx=mx.context.current_context())
    net.hybridize(static_alloc=True)

    x = mx.nd.random.uniform(shape=(1, 3, 32, 32))
    with mx.autograd.record(True):
        net(x)
    net(x)


def test_share_inputs_outputs():
    class TestIOBackward(gluon.HybridBlock):
        def __init__(self, prefix=None, params=None):
            super(TestIOBackward, self).__init__(prefix=prefix, params=params)

        def hybrid_forward(self, F, in1, in2):
            return in1 + in2

    class TestIOForward(gluon.HybridBlock):
        def __init__(self, prefix=None, params=None):
            super(TestIOForward, self).__init__(prefix=prefix, params=params)

        def hybrid_forward(self, F, in1):
            return in1

    d1 = mx.nd.arange(10)
    d2 = mx.nd.arange(10)

    params=[{'inline_limit':0},
            {'inline_limit':0, 'static_alloc':True},
            {'inline_limit':0, 'static_alloc':True, 'static_shape':True}]
    # Test the case that inputs and outputs of a forward graph share NDArrays.
    for param in params:
        t = TestIOForward()
        t.hybridize(**param)
        for i in range(5):
            d1.attach_grad()
            out_grad = mx.nd.random.uniform(shape=(10))
            res = t(d1)
            assert_almost_equal(res.asnumpy(), d1.asnumpy())

    param = deepcopy(params[2])
    param['param_indices'] = (1)
    param['data_indices'] = (0)
    params.append(param)
    # Test the case that inputs and outputs of a backward graph share NDArrays.
    for param in params:
        t = TestIOBackward()
        t.hybridize(**param)
        for i in range(5):
            d1.attach_grad()
            d2.attach_grad()
            out_grad = mx.nd.random.uniform(shape=(10))
            with mx.autograd.record():
                res = t(d1, d2)
            res.backward(out_grad=out_grad)
            assert_almost_equal(out_grad.asnumpy(), d1.grad.asnumpy())
            assert_almost_equal(out_grad.asnumpy(), d2.grad.asnumpy())


def test_grad_graph_change():
    class Model(mx.gluon.HybridBlock):
        def hybrid_forward(self, F, array, index):
            row = array.take(index)
            return row, index
    array = mx.nd.arange(3)
    index = mx.nd.array([2])
    array.attach_grad()
    model = Model()
    model.hybridize(inline_limit=0)
    with mx.autograd.record(train_mode=True):
        row, _ = model(array, index)
    row.backward()


if __name__ == '__main__':
    import nose
    nose.runmodule()
