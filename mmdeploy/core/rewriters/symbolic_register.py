import logging
from typing import Dict, Optional, Sequence

from mmcv.utils import Registry
from torch.autograd import Function
from torch.onnx.symbolic_helper import parse_args
from torch.onnx.symbolic_registry import register_op

from .register_utils import eval_with_import


def set_symbolic(cfg: Dict,
                 registry: Registry,
                 backend: str = 'default',
                 opset: int = 11,
                 **kwargs):
    """The build function of SYMBOLIC_REGISTER.

    Args:
        cfg (Dict): Config dictionary of deployment.
        registry (Registry): The registry to apply this build function.
        backend (str): The inference engine name.
        opset (int): The opset version of ONNX model.
    """

    # find valid symbolic
    valid_symbolic_dict = {}
    for module_name, symbolic_impl in registry.module_dict.items():
        func_name, symbolic_backend, is_pytorch = module_name.split('@')
        if symbolic_backend == backend or (symbolic_backend == 'default'
                                           and func_name
                                           not in valid_symbolic_dict):
            valid_symbolic_dict[func_name] = (symbolic_impl,
                                              is_pytorch == 'True')

    # build symbolic
    for func_name in valid_symbolic_dict:
        symbolic_impl, is_pytorch = valid_symbolic_dict[func_name]
        arg_descriptors = symbolic_impl.arg_descriptors
        symbolic_impl = symbolic_impl(cfg=cfg, **kwargs)
        if arg_descriptors is not None and len(arg_descriptors) > 0:
            symbolic_impl = parse_args(*arg_descriptors)(symbolic_impl)
        if is_pytorch:
            register_op(func_name, symbolic_impl, '', opset)
        else:
            try:
                func = eval_with_import(func_name)
                assert issubclass(
                    func,
                    Function), f'{func_name} is not an torch.autograd.Function'
                symbolic_impl.origin_func = getattr(func, 'symbolic', None)
                func.symbolic = symbolic_impl
            except Exception:
                logging.warning(f'Can not add symbolic for `{func_name}`')


SYMBOLIC_REGISTER = Registry('symbolics', build_func=set_symbolic, scope=None)


class SymbolicWrapper:
    """The wrapper of the symbolic function.

    The wrapper is used to pass context and environment to the symbolic.

    Args:
        cfg (Dict): Config dictionary of deployment.
    """
    func_name = ''
    backend = ''
    is_pytorch = False
    symbolic = None
    arg_descriptors = None

    def __init__(self, cfg: Dict, **kwargs):
        self.cfg = cfg

    def __call__(self, *args, **kwargs):
        return self.symbolic(*args, **kwargs)


def register_symbolic(func_name: str,
                      backend: str = 'default',
                      is_pytorch: bool = False,
                      arg_descriptors: Optional[Sequence[str]] = None,
                      **kwargs):
    """The decorator of the custom symbolic.

    Args:
        func_name (str): The function name/path to override the symbolic.
        backend (str): The inference engine name.
        is_pytorch (bool): Enable this flag if func_name is the name of \
            a pytorch builtin function.
        arg_descriptors (Sequence[str]): The argument descriptors of the \
            symbol.

    Returns:
        Callable: The process of registered symbolic.

    Examples:
        >>> @SYMBOLIC_REGISTER.register_symbolic('squeeze', is_pytorch=True)
        >>> def squeeze_default(ctx, g, self, dim=None):
        >>>     if dim is None:
        >>>         dims = []
        >>>         for i, size in enumerate(self.type().sizes()):
        >>>             if size == 1:
        >>>                 dims.append(i)
        >>>     else:
        >>>         dims = [sym_help._get_const(dim, 'i', 'dim')]
        >>>     return g.op('Squeeze', self, axes_i=dims)
    """

    def wrapper(symbolic_impl):
        symbolic_args = dict(
            func_name=func_name,
            backend=backend,
            symbolic=symbolic_impl,
            arg_descriptors=arg_descriptors)
        symbolic_args.update(kwargs)
        wrapper_name = '@'.join([func_name, backend, str(is_pytorch)])
        wrapper = type(wrapper_name, (SymbolicWrapper, ), symbolic_args)
        SYMBOLIC_REGISTER.register_module(wrapper_name)(wrapper)
        return symbolic_impl

    return wrapper


SYMBOLIC_REGISTER.register_symbolic = register_symbolic


def register_extra_symbolics(cfg: Dict,
                             backend: str = 'default',
                             opset: int = 11):
    """Enable custom symbolic with given config.

    Args:
        cfg (Dict): Config dictionary of deployment.
        backend (str): The inference engine name.
        opset (int): The opset version of ONNX model.
    """
    SYMBOLIC_REGISTER.build(cfg=cfg, backend=backend, opset=opset)
