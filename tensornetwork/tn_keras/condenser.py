import tensorflow as tf
from tensorflow.keras.layers import Layer  # type: ignore
from tensorflow.keras import activations
from tensorflow.keras import initializers
from typing import List, Optional, Text, Tuple
import tensornetwork as tn
from tensornetwork.network_components import Node
import numpy as np
import math


@tf.keras.utils.register_keras_serializable()  # type: ignore
class DenseCondenser(Layer):
  """Expander TN layer. Greatly expands dimensionality of input.
  Used in conjunction with DenseEntangler to achieve very large hidden layers.

  Example:

  ```python
  # as first layer in a sequential model:
  model = Sequential()
  model.add(
    DenseExpander(num_nodes=2,
                  use_bias=True,
                  activation='relu',
                  input_shape=(128,)))
  # now the model will take as input arrays of shape (*, 128)
  # and output arrays of shape (*, 2097152).
  # After the first layer, you don't need to specify
  # the size of the input anymore:
  model.add(DenseExpander(num_nodes=2, use_bias=True, activation='relu'))
  ```

  Args:
    num_nodes: Positive integer, number of nodes in expander.
      Note: the output dim will be input_shape[-1]**(num_nodes+1) so increasing
      num_nodes will increase the output dim exponentially.
    activation: Activation function to use.
      If you don't specify anything, no activation is applied
      (ie. "linear" activation: `a(x) = x`).
    use_bias: Boolean, whether the layer uses a bias vector.
    kernel_initializer: Initializer for the two weight matrices.
    bias_initializer: Initializer for the bias vector.

  Input shape:
    2D tensor with shape: `(batch_size, input_shape[-1])`.

  Output shape:
    2D tensor with shape: `(batch_size, input_shape[-1]**(num_nodes+1))`.
  """

  def __init__(self,
               num_nodes: int,
               use_bias: Optional[bool] = True,
               activation: Optional[Text] = None,
               kernel_initializer: Optional[Text] = 'glorot_uniform',
               bias_initializer: Optional[Text] = 'zeros',
               **kwargs) -> None:

    if 'input_shape' not in kwargs and 'input_dim' in kwargs:
      kwargs['input_shape'] = (kwargs.pop('input_dim'),)

    super(DenseCondenser, self).__init__(**kwargs)

    self.num_nodes = num_nodes
    self.nodes = []
    self.use_bias = use_bias
    self.activation = activations.get(activation)
    self.kernel_initializer = initializers.get(kernel_initializer)
    self.bias_initializer = initializers.get(bias_initializer)

  def build(self, input_shape: List[int]) -> None:
    # Disable the attribute-defined-outside-init violations in this function
    # pylint: disable=attribute-defined-outside-init
    if input_shape[-1] is None:
      raise ValueError('The last dimension of the inputs to `Dense` '
                       'should be defined. Found `None`.')

    super(DenseCondenser, self).build(input_shape)

    self.leg_dim = round(input_shape[-1]**(1. / (self.num_nodes + 1)))
    self.output_dim = self.leg_dim

    for i in range(self.num_nodes):
      self.nodes.append(
          self.add_weight(name=f'node_{i}',
                          shape=(self.leg_dim, self.leg_dim, self.leg_dim),
                          trainable=True,
                          initializer=self.kernel_initializer))

    self.bias_var = self.add_weight(
        name='bias',
        shape=(self.output_dim,),
        trainable=True,
        initializer=self.bias_initializer) if self.use_bias else None

  def call(self, inputs: tf.Tensor, **kwargs) -> tf.Tensor:  # pylint: disable=unused-argument

    def f(x: tf.Tensor, nodes: List[Node], num_nodes: int, use_bias: bool,
          bias_var: tf.Tensor) -> tf.Tensor:

      num_legs = num_nodes + 1
      l = [self.leg_dim] * num_legs
      print('leg_dim', self.leg_dim)
      print('x reshaped', tuple(l))
      input_reshaped = tf.reshape(x, tuple(l))
      state_node = tn.Node(input_reshaped, name='xnode', backend="tensorflow")

      for i in range(num_nodes):
        op = tn.Node(nodes[i], name=f'node_{i}', backend="tensorflow")
        tn.connect(state_node.edges[-1], op[0])
        tn.connect(state_node.edges[-2], op[1])
        state_node = tn.contract_between(state_node, op)
        
      # The TN will be connected like this:
      #      xxxxxxxxx
      #      | | |   |
      #      | | 11111
      #      | |   |
      #      | 22222
      #      |   |
      #      33333
      #        |
      #        |

      result = tf.reshape(state_node.tensor, (-1,))
      print('result shape', result.shape)
      if use_bias:
        result += bias_var

      return result

    result = tf.vectorized_map(
        lambda vec: f(vec, self.nodes, self.num_nodes, self.use_bias, self.
                      bias_var), inputs)
    if self.activation is not None:
      result = self.activation(result)
    return tf.reshape(result, (-1, self.output_dim))

  def compute_output_shape(self, input_shape: List[int]) -> Tuple[int, int]:
    return (input_shape[0], self.output_dim)

  def get_config(self) -> dict:
    """Returns the config of the layer.

    The same layer can be reinstantiated later
    (without its trained weights) from this configuration.

    Returns:
      Python dictionary containing the configuration of the layer.
    """
    config = {}

    # Include the Condenser-specific arguments
    expander_args = ['num_nodes', 'use_bias']
    for arg in expander_args:
      config[arg] = getattr(self, arg)

    # Serialize the activation
    config['activation'] = activations.serialize(getattr(self, 'activation'))

    # Serialize the initializers
    mpo_initializers = ['kernel_initializer', 'bias_initializer']
    for initializer_arg in mpo_initializers:
      config[initializer_arg] = initializers.serialize(
          getattr(self, initializer_arg))

    # Get base config
    base_config = super(DenseCondenser, self).get_config()
    return dict(list(base_config.items()) + list(config.items()))
