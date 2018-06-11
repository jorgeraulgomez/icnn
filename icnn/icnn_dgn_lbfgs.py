#! /usr/bin/env python
# -*- coding: utf-8 -*-

'''invert CNN feature to reconstruct image'''

# Author: Shen Guo-Hua <shen-gh@atr.jp>

__author__ = 'sgh'


# v8_3_5
# recon img from cnn feat
# for multiple layers
# optimize in the feature space of a generator net
# use ’L-BFGS-B’ as optimization method
# output loss list

# import
import numpy as np
import caffe
from scipy.optimize import minimize

from .utils import img_deprocess, sort_layer_list, create_feature_masks
from .loss import switch_loss_fun


# main function
def reconstruct_image(features, net, net_gen,
                      layer_weight = None,
                      channel = None, mask = None,
                      initial_gen_feat = None,
                      gen_feat_bounds = None,
                      input_layer_gen = None, output_layer_gen = None,
                      loss_type = 'l2', maxiter = 500, disp = True
                      ):
    
    ''' Reconstruct image from CNN features using L-BFGS-B.
        Constrain the reconstrcuted image via a deep generator net.
    
    Parameters
    ----------
    features: dict
        The target CNN features.
        The CNN features of multiple layers are assembled in a python dictionary, arranged in pairs of layer name (key) and CNN features (value).
    net: caffe.Classifier or caffe.Net object
        CNN model coresponding to the target CNN features.
    net_gen: caffe.Net object
        Deep generator net.
    
    Optional Parameters
    ----------
    layer_weight: dict
        The weight for each layer in the loss function.
        The weights of multiple layers are assembled in a python dictionary, arranged in pairs of layer name (key) and weight(value).
        Use equal weights for all layers by setting to None. 
    channel: dict
        The channel numbers of each layer to be used in the loss function.
        The channels of multiple layers are assembled in a python dictionary, arranged in pairs of layer name (key) and channel numbers(value).
        Use all the channels if some layer is not in the dictionary.
        Use all channels for all layers by setting to None.
    mask: dict
        Masks of CNN features,
        Which select units for each layer to be used in the loss function (1: using the uint; 0: excluding the unit).
        The masks of multiple layers are assembled in a python dictionary, arranged in pairs of layer name (key) and mask (value).
        Use all the units if some layer is not in the dictionary.
        using all units for all layers by setting to None.
    initial_gen_feat: ndarray
        Initial features of the input layer of the generator.
        Use random noise as initial features by setting to None.
    gen_feat_bounds: list
        (min, max) pairs for each unit in the input layer of the generator, defining the boundary on the units.
        Use None or +-inf for one of min or max when there is no bound in that direction.
        Use (0, 100) as default bounds for each unit if gen_feat_bounds=None.
    input_layer_gen: str
        The name of the input layer of the generator.
    output_layer_gen: str
        The name of the output layer of the generator.
    loss_type: str
        The loss function type: {'l2','l1','inner','gram'}.
    maxiter: int
        The maximum number of iterations.
    disp: bool
        Display the optimization information or not.
    
    Returns
    -------
    img: ndarray
        The reconstructed image [227x227x3].
    loss_list: ndarray
        The loss for each iteration.
        It is 1 dimensional array of the value of the loss for each iteration.  
    '''
    
    # loss function
    loss_fun = switch_loss_fun(loss_type)
    
    # input and output layers of the generator
    gen_layer_list = net_gen.blobs.keys()
    if input_layer_gen is None:
        input_layer_gen = gen_layer_list[0]
    if output_layer_gen is None:
        output_layer_gen = gen_layer_list[-1]
    
    # gen feature size
    feat_gen_size = net_gen.blobs[input_layer_gen].data.shape[1:]
    
    # initial gen feature
    if initial_gen_feat is None:
        initial_gen_feat = np.random.normal(0, 1, feat_gen_size)
        initial_gen_feat = np.float32(initial_gen_feat)
    
    # gen feature bounds
    if gen_feat_bounds is None:
        num_of_unit = np.prod(feat_gen_size)
        gen_feat_bounds = []
        for j in xrange(num_of_unit):
            gen_feat_bounds.append((0.,100.)) # as default, lower bound is 0, upper bound is 100.
    
    # image size
    img_size = net.blobs['data'].data.shape[-3:]
    img_size_gen = net_gen.blobs[output_layer_gen].data.shape[-3:]
    
    # top left offset for cropping the output image to get the 224x224 image
    top_left = ((img_size_gen[1] - img_size[1])/2,(img_size_gen[2] - img_size[2])/2)
    
    # image mean
    img_mean = net.transformer.mean['data']
    
    # layer_list
    layer_list = features.keys()
    layer_list = sort_layer_list(net,layer_list)
    
    # number of layers
    num_of_layer = len(layer_list)
    
    # layer weight
    if layer_weight is None:
        weights = np.ones(num_of_layer)
        weights = np.float32(weights)
        weights = weights / weights.sum()
        layer_weight = {}
        for j, layer in enumerate(layer_list):
            layer_weight[layer] = weights[j]
    
    # feature mask
    feature_masks = create_feature_masks(features, masks=mask, channels=channel)
    
    # optimization params
    loss_list = []
    opt_params = {
                'args': (net, features, feature_masks, layer_weight, net_gen, input_layer_gen, output_layer_gen, loss_fun, loss_list),
                
                'method': 'L-BFGS-B',
                
                'jac': True,
                
                'bounds': gen_feat_bounds,
                
                'options': {'maxiter': maxiter, 'disp': disp},                
                }
    
    # optimization
    #global loss_list
    #loss_list = []
    res = minimize(obj_fun,initial_gen_feat.flatten(),**opt_params)
    
    # feat_gen
    feat_gen = res.x
    
    # reshape gen feat
    feat_gen = feat_gen.reshape(feat_gen_size)
    
    # generator forward
    net_gen.blobs[input_layer_gen].data[0] = feat_gen.copy()
    net_gen.forward()
    
    # generated image
    img0 = net_gen.blobs[output_layer_gen].data[0].copy()
    
    # crop image
    img = img0[:,top_left[0]:top_left[0]+img_size[1],top_left[1]:top_left[1]+img_size[2]].copy()
    
    # return img
    return img_deprocess(img,img_mean), loss_list

# objective function
#loss_list = []
def obj_fun(feat_gen, net, features, feature_masks, layer_weight, net_gen, input_layer_gen, output_layer_gen, loss_fun, loss_list = []): 
    #
    #global loss_list
    
    # reshape feat_gen
    feat_gen_size = net_gen.blobs[input_layer_gen].data.shape[1:]
    feat_gen = feat_gen.reshape(feat_gen_size)
    
    # generator forward
    net_gen.blobs[input_layer_gen].data[0] = feat_gen.copy()
    net_gen.forward()
    
    # generated image
    img0 = net_gen.blobs[output_layer_gen].data[0].copy()
    
    # crop image
    img_size = net.blobs['data'].data.shape[-3:]
    img_size_gen = net_gen.blobs[output_layer_gen].data.shape[-3:]
    top_left = ((img_size_gen[1] - img_size[1])/2,(img_size_gen[2] - img_size[2])/2)
    img = img0[:,top_left[0]:top_left[0]+img_size[1],top_left[1]:top_left[1]+img_size[2]].copy()
    
    # layer_list
    layer_list = features.keys()
    layer_list = sort_layer_list(net,layer_list)
    
    # num_of_layer
    num_of_layer = len(layer_list)
    
    # cnn forward
    net.blobs['data'].data[0] = img.copy()
    net.forward(end=layer_list[-1])
    
    # cnn backward
    loss = 0.
    layer_start = layer_list[-1]
    net.blobs[layer_start].diff.fill(0.)
    for j in xrange(num_of_layer):
        layer_start_index = num_of_layer - 1 - j
        layer_end_index = num_of_layer - 1 - j - 1
        layer_start = layer_list[layer_start_index]
        if layer_end_index>=0:
            layer_end = layer_list[layer_end_index]
        else:
            layer_end = 'data'
        feat_j = net.blobs[layer_start].data[0].copy()
        feat0_j = features[layer_start]
        mask_j = feature_masks[layer_start]
        layer_weight_j = layer_weight[layer_start]
        loss_j, grad_j = loss_fun(feat_j,feat0_j,mask_j)
        loss_j = layer_weight_j * loss_j
        grad_j = layer_weight_j * grad_j
        loss = loss + loss_j
        g = net.blobs[layer_start].diff[0].copy()
        g = g + grad_j
        net.blobs[layer_start].diff[0] = g.copy()
        if layer_end=='data':
            net.backward(start=layer_start)
        else:
            net.backward(start=layer_start,end=layer_end)
        net.blobs[layer_start].diff.fill(0.)
    grad = net.blobs['data'].diff[0].copy()
    
    # generator backward
    grad0 = np.zeros_like(net_gen.blobs[output_layer_gen].diff[0])
    grad0[:,top_left[0]:top_left[0]+img_size[1],top_left[1]:top_left[1]+img_size[2]] = grad.copy()
    net_gen.blobs[output_layer_gen].diff[0] = grad0.copy()
    net_gen.backward()
    net_gen.blobs[output_layer_gen].diff.fill(0.)
    grad = net_gen.blobs[input_layer_gen].diff[0].copy()
    
    # reshape gradient
    grad = grad.flatten().astype(np.float64)
    
    #
    loss_list.append(loss)
    
    return loss, grad

