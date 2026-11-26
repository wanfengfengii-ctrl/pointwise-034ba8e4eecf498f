from cuts.revisions import RevisionStore
from releases.cues import build_cue_sheet
from releases.eligibility import (
    require_ready_review,
    require_same_revision_confirmation,
    revision_has_review,
)
from releases.packages import PackageStore
from render.wave import encode_wave
from workspace import transaction


class UnknownReleaseRevision(LookupError):
    pass


def issue_release(connection, renderer, sample_rate, revision_id, body):
    with transaction(connection):
        revision = RevisionStore(connection).get(revision_id)
        if revision is None:
            raise UnknownReleaseRevision('unknown revision')

        if revision_has_review(connection, revision_id):
            # Once carry handling exists for this revision, only its own
            # ready verdict can issue a package; old confirmations cannot
            # bypass the outstanding seams.
            verdict = require_ready_review(connection, revision, body.get('review_id'))
            confirmation_id = None
            review_id = verdict.review_id
        else:
            confirmation = require_same_revision_confirmation(
                connection, revision, body.get('confirmation_id')
            )
            confirmation_id = confirmation.confirmation_id
            review_id = None

        samples = renderer.render_strict(revision, 0, revision.total_frames)
        wav = encode_wave(samples, sample_rate)
        cue_sheet = build_cue_sheet(revision, sample_rate)
        package = PackageStore(connection).insert_package(
            revision.revision_id, confirmation_id, cue_sheet, wav, review_id=review_id
        )
    return package
