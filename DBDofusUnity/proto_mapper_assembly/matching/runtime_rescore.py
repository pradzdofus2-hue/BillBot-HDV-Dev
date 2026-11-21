from typing import NamedTuple

import numpy as np
from tqdm import tqdm

from DBDofusUnity.proto_mapper_assembly.field_mapping.field_mapper import build_field_mapping
from DBDofusUnity.proto_mapper_assembly.interfaces.field_mapping import FieldMappingContext
from DBDofusUnity.proto_mapper_assembly.interfaces.matching import MatchingWorkspace
from DBDofusUnity.proto_mapper_assembly.interfaces.matching_inputs import MatchingInputs, MatchingRunConfig
from DBDofusUnity.proto_mapper_assembly.interfaces.message_pair import MatchPairKey
from DBDofusUnity.proto_mapper_assembly.matching.score_lookup import (
    build_lazy_score_by_pair_lookup_from_matrix,
)
from DBDofusUnity.proto_mapper_assembly.runtime.runtime_field_validation import (
    build_runtime_field_validator_confidence,
)

_RUNTIME_GUARANTEED_TOP_CANDIDATE_COUNT = 3
_RUNTIME_MAX_CANDIDATE_COUNT = 10
_RUNTIME_MAX_STATIC_SCORE_GAP_FROM_BEST = 0.10
_VALIDATED_RUNTIME_BONUS_RATE = 0.10


class RuntimeCandidateIndexes(NamedTuple):
    non_obf_index: int
    obf_index: int


class RuntimeRescoredScores(NamedTuple):
    scores_matrix: np.ndarray
    runtime_confidence_by_pair: dict[MatchPairKey, float]
    rejected_candidate_indexes: list[RuntimeCandidateIndexes]


def build_runtime_rescored_scores(
    *,
    workspace: MatchingWorkspace,
    inputs: MatchingInputs,
    run_config: MatchingRunConfig,
    scores_matrix: np.ndarray,
) -> RuntimeRescoredScores:
    """Rescore only capture-backed candidates; absent runtime evidence is neutral."""
    rescored_matrix = np.array(scores_matrix, copy=True)
    runtime_confidence_by_pair: dict[MatchPairKey, float] = {}
    rejected_candidate_indexes: list[RuntimeCandidateIndexes] = []
    field_mapping_context = FieldMappingContext(
        score_by_pair=build_lazy_score_by_pair_lookup_from_matrix(
            workspace=workspace, scores_matrix=scores_matrix
        ),
        runtime_data_store=run_config.runtime_data_store,
        signature_overrides_by_non_obf_cls=inputs.signature_overrides_by_non_obf_cls,
        obf_enum_signatures_by_name=inputs.obf_enum_signatures_by_name,
        non_obf_enum_signatures_by_name=inputs.non_obf_enum_signatures_by_name,
        obf_access_trace=inputs.obf_access_trace,
        non_obf_access_trace=inputs.non_obf_access_trace,
    )
    pins = run_config.pinned_pairs_config
    for indexes in tqdm(_iter_runtime_candidate_indexes(scores_matrix)):
        non_obf_index, obf_index = indexes
        obf_signature = workspace.obf_signatures[obf_index]
        non_obf_signature = workspace.non_obf_signatures[non_obf_index]
        obf_cls = obf_signature.message_cls
        non_obf_cls = non_obf_signature.message_cls
        pinned_pair = pins.pinned_pair_msg_by_obf.get(obf_cls)
        if pinned_pair is None:
            assert non_obf_cls not in pins.pinned_pair_msg_by_non_obf
        else:
            assert pinned_pair.non_obf == non_obf_cls

        field_mapping_result = build_field_mapping(
            non_obf_signature=non_obf_signature,
            obf_signature=obf_signature,
            non_obf_messages_by_cls=inputs.non_obf_messages_by_cls,
            obf_messages_by_cls=inputs.obf_messages_by_cls,
            field_mapping_context=field_mapping_context,
            obf_type_index=workspace.obf_type_index,
            non_obf_type_index=workspace.non_obf_type_index,
            pinned_pair=pinned_pair,
        )
        runtime_confidence = build_runtime_field_validator_confidence(
            field_mapping=field_mapping_result.field_mapping,
            obf_message=inputs.obf_messages_by_cls[obf_cls],
            obf_messages_by_cls=inputs.obf_messages_by_cls,
            non_obf_message=inputs.non_obf_messages_by_cls[non_obf_cls],
            validated_non_obf_field_names={
                field.clean_field_name for field in non_obf_signature.get_exportable_fields()
            },
            runtime_data_store=run_config.runtime_data_store,
        )
        if field_mapping_result.has_validation_failure:
            runtime_confidence = 0.0
            rejected_candidate_indexes.append(indexes)

        rescored_matrix[non_obf_index, obf_index] = _apply_runtime_confidence_score(
            static_similarity=float(scores_matrix[non_obf_index, obf_index]),
            runtime_confidence=runtime_confidence,
        )
        if runtime_confidence is not None:
            runtime_confidence_by_pair[MatchPairKey(obf_cls, non_obf_cls)] = runtime_confidence

    return RuntimeRescoredScores(rescored_matrix, runtime_confidence_by_pair, rejected_candidate_indexes)


def _iter_runtime_candidate_indexes(
    scores_matrix: np.ndarray,
) -> tuple[RuntimeCandidateIndexes, ...]:
    candidate_indexes: list[RuntimeCandidateIndexes] = []
    for obf_index in range(scores_matrix.shape[1]):
        obf_scores = scores_matrix[:, obf_index]
        best_score = float(obf_scores.max())
        if best_score <= 0.0:
            continue
        ranked_non_obf_indexes = np.argsort(obf_scores)[::-1]
        for candidate_rank, non_obf_index_value in enumerate(
            ranked_non_obf_indexes[:_RUNTIME_MAX_CANDIDATE_COUNT]
        ):
            non_obf_index = int(non_obf_index_value)
            candidate_score = float(obf_scores[non_obf_index])
            if candidate_score <= 0.0:
                continue
            if (
                candidate_rank >= _RUNTIME_GUARANTEED_TOP_CANDIDATE_COUNT
                and candidate_score < best_score - _RUNTIME_MAX_STATIC_SCORE_GAP_FROM_BEST
            ):
                continue
            candidate_indexes.append(RuntimeCandidateIndexes(non_obf_index, obf_index))
    return tuple(candidate_indexes)


def _apply_runtime_confidence_score(*, static_similarity: float, runtime_confidence: float | None) -> float:
    if runtime_confidence is None:
        return static_similarity
    if runtime_confidence <= 0.0:
        return 0.0
    return static_similarity * (1.0 + runtime_confidence * _VALIDATED_RUNTIME_BONUS_RATE)
