"""Use cases for carry confirmations and review verdicts."""
from auditions.evidence import EvidenceStore
from auditions.sessions import AuditionStore, UnknownAudition
from cuts.revisions import RevisionStore
from reviews.analysis import build_verdict
from reviews.store import NoActualOutput, ReviewConfirmationStore, ReviewStore
from workspace import transaction


class UnknownReviewTarget(LookupError):
    pass


class UnknownSelectedAudition(LookupError):
    pass


class RootRevisionTarget(ValueError):
    pass


class UnconfirmedSelection(ValueError):
    pass


class SelectionOutOfScope(ValueError):
    pass


def confirm_audition_for_review(connection, audition_id):
    store = ReviewConfirmationStore(connection)
    with transaction(connection):
        existing = store.get(audition_id)
        if existing is not None:
            # Re-claim the original frozen confirmation; later output and
            # cache reclamation never alter it.
            return existing

        audition = AuditionStore(connection).get(audition_id)
        if audition is None:
            raise UnknownAudition('unknown audition')

        evidence = EvidenceStore(connection).get(audition_id)
        runs = evidence.runs if evidence is not None else ()
        if not runs:
            # Old merged progress, seek/pause-only sessions and pure fill
            # output carry no usable real continuous evidence.
            raise NoActualOutput('audition has no real output to confirm')

        return store.freeze(audition_id, audition.revision_id, runs)


def create_review(connection, target_revision_id, audition_ids):
    revisions = RevisionStore(connection)
    auditions = AuditionStore(connection)
    confirmations = ReviewConfirmationStore(connection)
    review_store = ReviewStore(connection)

    with transaction(connection):
        target = revisions.get(target_revision_id)
        if target is None:
            raise UnknownReviewTarget('unknown target revision')
        if target.parent_revision_id is None:
            raise RootRevisionTarget('only revisions with a direct parent can carry reviews')

        evidence = []
        for audition_id in audition_ids:
            audition = auditions.get(audition_id)
            if audition is None:
                raise UnknownSelectedAudition('unknown audition in selection')
            confirmation = confirmations.get(audition_id)
            if confirmation is None:
                raise UnconfirmedSelection('every selected audition must be review-confirmed')
            if audition.revision_id not in (target.revision_id, target.parent_revision_id):
                raise SelectionOutOfScope(
                    'selected audition must belong to the target revision or its direct parent'
                )
            revision = revisions.get(confirmation.revision_id)
            evidence.append((revision, confirmation.runs))

        unheard, missing_seams, ready = build_verdict(target, evidence)
        verdict = review_store.insert(
            target.revision_id, audition_ids, unheard, missing_seams, ready
        )
    return verdict
