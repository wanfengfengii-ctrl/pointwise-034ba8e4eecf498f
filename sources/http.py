from http_support import Problem
from sources.imports import import_asset


def post_asset(connection, sample_rate, body):
    try:
        asset = import_asset(
            connection, sample_rate, body.get('source'), body.get('sample_rate'), body.get('samples')
        )
    except ValueError as error:
        raise Problem(400, str(error)) from error
    return {
        'asset_id': asset.asset_id,
        'source': asset.source,
        'sample_rate': asset.sample_rate,
        'frames': asset.frames,
    }
