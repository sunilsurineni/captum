#!/usr/bin/env python3
import typing
from inspect import signature
from typing import TYPE_CHECKING, Any, Callable, List, Tuple, Union

import torch
from torch import Tensor

from ..._utils.common import _format_input
from ..._utils.typing import (
    BaselineType,
    Literal,
    TargetType,
    TensorOrTupleOfTensorsGeneric,
)
from .approximation_methods import SUPPORTED_METHODS

if TYPE_CHECKING:
    from .attribution import GradientAttribution


def _validate_target(num_samples: int, target: TargetType) -> None:
    if isinstance(target, list) or (
        isinstance(target, torch.Tensor) and torch.numel(target) > 1
    ):
        assert num_samples == len(target), (
            "The number of samples provied in the"
            "input {} does not match with the number of targets. {}".format(
                num_samples, len(target)
            )
        )


def _validate_input(
    inputs: Tuple[Tensor, ...],
    baselines: Tuple[Union[Tensor, int, float], ...],
    n_steps: int = 50,
    method: str = "riemann_trapezoid",
    draw_baseline_from_distrib: bool = False,
) -> None:
    assert len(inputs) == len(baselines), (
        "Input and baseline must have the same "
        "dimensions, baseline has {} features whereas input has {}.".format(
            len(baselines), len(inputs)
        )
    )

    for input, baseline in zip(inputs, baselines):
        if draw_baseline_from_distrib:
            assert (
                isinstance(baseline, (int, float))
                or input.shape[1:] == baseline.shape[1:]
            ), (
                "The samples in input and baseline batches must have"
                " the same shape or the baseline corresponding to the"
                " input tensor must be a scalar."
                " Found baseline: {} and input: {} ".format(baseline, input)
            )
        else:
            assert (
                isinstance(baseline, (int, float))
                or input.shape == baseline.shape
                or baseline.shape[0] == 1
            ), (
                "Baseline can be provided as a tensor for just one input and"
                " broadcasted to the batch or input and baseline must have the"
                " same shape or the baseline corresponding to each input tensor"
                " must be a scalar. Found baseline: {} and input: {}".format(
                    baseline, input
                )
            )

    assert (
        n_steps >= 0
    ), "The number of steps must be a positive integer. " "Given: {}".format(n_steps)

    assert method in SUPPORTED_METHODS, (
        "Approximation method must be one for the following {}. "
        "Given {}".format(SUPPORTED_METHODS, method)
    )


def _validate_noise_tunnel_type(
    nt_type: str, supported_noise_tunnel_types: List[str]
) -> None:
    assert nt_type in supported_noise_tunnel_types, (
        "Noise types must be either `smoothgrad`, `smoothgrad_sq` or `vargrad`. "
        "Given {}".format(nt_type)
    )


def _format_baseline(
    baselines: BaselineType, inputs: Tuple[Tensor, ...]
) -> Tuple[Union[Tensor, int, float], ...]:
    if baselines is None:
        return _zeros(inputs)

    if not isinstance(baselines, tuple):
        baselines = (baselines,)

    for baseline in baselines:
        assert isinstance(
            baseline, (torch.Tensor, int, float)
        ), "baseline input argument must be either a torch.Tensor or a number \
            however {} detected".format(
            type(baseline)
        )

    return baselines


@typing.overload
def _format_input_baseline(
    inputs: Union[Tensor, Tuple[Tensor, ...]],
    baselines: Union[Tensor, Tuple[Tensor, ...]],
) -> Tuple[Tuple[Tensor, ...], Tuple[Tensor, ...]]:
    ...


@typing.overload
def _format_input_baseline(
    inputs: Union[Tensor, Tuple[Tensor, ...]], baselines: BaselineType
) -> Tuple[Tuple[Tensor, ...], Tuple[Union[Tensor, int, float], ...]]:
    ...


def _format_input_baseline(
    inputs: Union[Tensor, Tuple[Tensor, ...]], baselines: BaselineType
) -> Tuple[Tuple[Tensor, ...], Tuple[Union[Tensor, int, float], ...]]:
    inputs = _format_input(inputs)
    baselines = _format_baseline(baselines, inputs)
    return inputs, baselines


# This function can potentially be merged with the `format_baseline` function
# however, since currently not all algorithms support baselines of type
# callable this will be kept in a separate function.
@typing.overload
def _format_callable_baseline(
    baselines: Union[
        None,
        Callable[..., Union[Tensor, Tuple[Tensor, ...]]],
        Tensor,
        Tuple[Tensor, ...],
    ],
    inputs: Union[Tensor, Tuple[Tensor, ...]],
) -> Tuple[Tensor, ...]:
    ...


@typing.overload
def _format_callable_baseline(
    baselines: Union[
        None,
        Callable[..., Union[Tensor, Tuple[Tensor, ...]]],
        Tensor,
        int,
        float,
        Tuple[Union[Tensor, int, float], ...],
    ],
    inputs: Union[Tensor, Tuple[Tensor, ...]],
) -> Tuple[Union[Tensor, int, float], ...]:
    ...


def _format_callable_baseline(
    baselines: Union[
        None,
        Callable[..., Union[Tensor, Tuple[Tensor, ...]]],
        Tensor,
        int,
        float,
        Tuple[Union[Tensor, int, float], ...],
    ],
    inputs: Union[Tensor, Tuple[Tensor, ...]],
) -> Tuple[Union[Tensor, int, float], ...]:
    if callable(baselines):
        # Note: this assumes that if baselines is a function and if it takes
        # arguments, then the first argument is the `inputs`.
        # This can be expanded in the future with better type checks
        baseline_parameters = signature(baselines).parameters
        if len(baseline_parameters) == 0:
            baselines = baselines()
        else:
            baselines = baselines(inputs)
    return _format_baseline(baselines, _format_input(inputs))


@typing.overload
def _format_attributions(
    is_inputs_tuple: Literal[True], attributions: Tuple[Tensor, ...]
) -> Tuple[Tensor, ...]:
    ...


@typing.overload
def _format_attributions(
    is_inputs_tuple: Literal[False], attributions: Tuple[Tensor, ...]
) -> Tensor:
    ...


@typing.overload
def _format_attributions(
    is_inputs_tuple: bool, attributions: Tuple[Tensor, ...]
) -> Union[Tensor, Tuple[Tensor, ...]]:
    ...


def _format_attributions(
    is_inputs_tuple: bool, attributions: Tuple[Tensor, ...]
) -> Union[Tensor, Tuple[Tensor, ...]]:
    r"""
    In case input is a tensor and the attributions is returned in form of a
    tensor we take the first element of the attributions' tuple to match the
    same shape signatues of the inputs
    """
    assert isinstance(attributions, tuple), "Attributions must be in shape of a tuple"
    assert is_inputs_tuple or len(attributions) == 1, (
        "The input is a single tensor however the attributions aren't."
        "The number of attributed tensors is: {}".format(len(attributions))
    )
    return attributions if is_inputs_tuple else attributions[0]


def _format_and_verify_strides(
    strides: Union[None, int, Tuple[int, ...], Tuple[Union[int, Tuple[int, ...]], ...]],
    inputs: Tuple[Tensor, ...],
) -> Tuple[Union[int, Tuple[int, ...]], ...]:
    # Formats strides, which are necessary for occlusion
    # Assumes inputs are already formatted (in tuple)
    if strides is None:
        strides = tuple(1 for input in inputs)
    if len(inputs) == 1 and not (isinstance(strides, tuple) and len(strides) == 1):
        strides = (strides,)  # type: ignore
    assert isinstance(strides, tuple) and len(strides) == len(
        inputs
    ), "Strides must be provided for each input tensor."
    for i in range(len(inputs)):
        assert isinstance(strides[i], int) or (
            isinstance(strides[i], tuple)
            and len(strides[i]) == len(inputs[i].shape) - 1  # type: ignore
        ), (
            "Stride for input index {} is {}, which is invalid for input with "
            "shape {}. It must be either an int or a tuple with length equal to "
            "len(input_shape) - 1."
        ).format(
            i, strides[i], inputs[i].shape
        )

    return strides


def _format_and_verify_sliding_window_shapes(
    sliding_window_shapes: Union[Tuple[int, ...], Tuple[Tuple[int, ...], ...]],
    inputs: Tuple[Tensor, ...],
) -> Tuple[Tuple[int, ...], ...]:
    # Formats shapes of sliding windows, which is necessary for occlusion
    # Assumes inputs is already formatted (in tuple)
    if isinstance(sliding_window_shapes[0], int):
        sliding_window_shapes = (sliding_window_shapes,)  # type: ignore
    sliding_window_shapes: Tuple[Tuple[int, ...], ...]
    assert len(sliding_window_shapes) == len(
        inputs
    ), "Must provide sliding window dimensions for each input tensor."
    for i in range(len(inputs)):
        assert (
            isinstance(sliding_window_shapes[i], tuple)
            and len(sliding_window_shapes[i]) == len(inputs[i].shape) - 1
        ), (
            "Occlusion shape for input index {} is {} but should be a tuple with "
            "{} dimensions."
        ).format(
            i, sliding_window_shapes[i], len(inputs[i].shape) - 1
        )
    return sliding_window_shapes


@typing.overload
def _compute_conv_delta_and_format_attrs(
    attr_algo: "GradientAttribution",
    return_convergence_delta: bool,
    attributions: Tuple[Tensor, ...],
    start_point: Union[int, float, Tensor, Tuple[Union[int, float, Tensor], ...]],
    end_point: Union[Tensor, Tuple[Tensor, ...]],
    additional_forward_args: Any,
    target: TargetType,
    is_inputs_tuple: Literal[False] = False,
) -> Union[Tensor, Tuple[Tensor, Tensor]]:
    ...


@typing.overload
def _compute_conv_delta_and_format_attrs(
    attr_algo: "GradientAttribution",
    return_convergence_delta: bool,
    attributions: Tuple[Tensor, ...],
    start_point: Union[int, float, Tensor, Tuple[Union[int, float, Tensor], ...]],
    end_point: Union[Tensor, Tuple[Tensor, ...]],
    additional_forward_args: Any,
    target: TargetType,
    is_inputs_tuple: Literal[True],
) -> Union[Tuple[Tensor, ...], Tuple[Tuple[Tensor, ...], Tensor]]:
    ...


# FIXME: GradientAttribution is provided as a string due to a circular import.
# This should be fixed when common is refactored into separate files.
def _compute_conv_delta_and_format_attrs(
    attr_algo: "GradientAttribution",
    return_convergence_delta: bool,
    attributions: Tuple[Tensor, ...],
    start_point: Union[int, float, Tensor, Tuple[Union[int, float, Tensor], ...]],
    end_point: Union[Tensor, Tuple[Tensor, ...]],
    additional_forward_args: Any,
    target: TargetType,
    is_inputs_tuple: bool = False,
) -> Union[
    Tensor, Tuple[Tensor, ...], Tuple[Union[Tensor, Tuple[Tensor, ...]], Tensor]
]:
    if return_convergence_delta:
        # computes convergence error
        delta = attr_algo.compute_convergence_delta(
            attributions,
            start_point,
            end_point,
            additional_forward_args=additional_forward_args,
            target=target,
        )
        return _format_attributions(is_inputs_tuple, attributions), delta
    else:
        return _format_attributions(is_inputs_tuple, attributions)


def _zeros(inputs: Tuple[Tensor, ...]) -> Tuple[int, ...]:
    r"""
    Takes a tuple of tensors as input and returns a tuple that has the same
    length as `inputs` with each element as the integer 0.
    """
    return tuple(0 for input in inputs)


def _tensorize_baseline(
    inputs: Tuple[Tensor, ...], baselines: Tuple[Union[int, float, Tensor], ...]
) -> Tuple[Tensor, ...]:
    def _tensorize_single_baseline(baseline, input):
        if isinstance(baseline, (int, float)):
            return torch.full_like(input, baseline)
        if input.shape[0] > baseline.shape[0] and baseline.shape[0] == 1:
            return torch.cat([baseline] * input.shape[0])
        return baseline

    assert isinstance(inputs, tuple) and isinstance(baselines, tuple), (
        "inputs and baselines must"
        "have tuple type but found baselines: {} and inputs: {}".format(
            type(baselines), type(inputs)
        )
    )
    return tuple(
        _tensorize_single_baseline(baseline, input)
        for baseline, input in zip(baselines, inputs)
    )


def _reshape_and_sum(
    tensor_input: Tensor, num_steps: int, num_examples: int, layer_size: Tuple[int, ...]
) -> Tensor:
    # Used for attribution methods which perform integration
    # Sums across integration steps by reshaping tensor to
    # (num_steps, num_examples, (layer_size)) and summing over
    # dimension 0. Returns a tensor of size (num_examples, (layer_size))
    return torch.sum(
        tensor_input.reshape((num_steps, num_examples) + layer_size), dim=0
    )


def _call_custom_attribution_func(
    custom_attribution_func: Callable[..., Tuple[Tensor, ...]],
    multipliers: Tuple[Tensor, ...],
    inputs: Tuple[Tensor, ...],
    baselines: Tuple[Tensor, ...],
) -> Tuple[Tensor, ...]:
    assert callable(custom_attribution_func), (
        "`custom_attribution_func`"
        " must be a callable function but {} provided".format(
            type(custom_attribution_func)
        )
    )
    custom_attr_func_params = signature(custom_attribution_func).parameters

    if len(custom_attr_func_params) == 1:
        return custom_attribution_func(multipliers)
    elif len(custom_attr_func_params) == 2:
        return custom_attribution_func(multipliers, inputs)
    elif len(custom_attr_func_params) == 3:
        return custom_attribution_func(multipliers, inputs, baselines)
    else:
        raise AssertionError(
            "`custom_attribution_func` must take at least one and at most 3 arguments."
        )


def _find_output_mode_and_verify(
    initial_eval: Union[int, float, Tensor],
    num_examples: int,
    perturbations_per_eval: int,
    feature_mask: Union[None, TensorOrTupleOfTensorsGeneric],
) -> bool:
    """
    This method identifies whether the model outputs a single output for a batch
    (agg_output_mode = True) or whether it outputs a single output per example
    (agg_output_mode = False) and returns agg_output_mode. The method also
    verifies that perturbations_per_eval is 1 in the case that agg_output_mode is True
    and also verifies that the first dimension of each feature mask if the model
    returns a single output for a batch.
    """
    if isinstance(initial_eval, (int, float)) or (
        isinstance(initial_eval, torch.Tensor)
        and (
            len(initial_eval.shape) == 0
            or (num_examples > 1 and initial_eval.numel() == 1)
        )
    ):
        agg_output_mode = True
        assert (
            perturbations_per_eval == 1
        ), "Cannot have perturbations_per_eval > 1 when function returns scalar."
        if feature_mask is not None:
            for single_mask in feature_mask:
                assert single_mask.shape[0] == 1, (
                    "Cannot provide different masks for each example when function "
                    "returns a scalar."
                )
    else:
        agg_output_mode = False
        assert (
            isinstance(initial_eval, torch.Tensor) and initial_eval[0].numel() == 1
        ), "Target should identify a single element in the model output."
    return agg_output_mode
