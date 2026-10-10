"""Public independent validation dispatch for both solver result schemas."""
from . import validation_ordinary, validation_3d


def validate(request, result, diagnostics=False):
    """Return a list of reasons an original request/result pair is unverified."""
    try:
        schema = result.get('schema_version', 1) if isinstance(result, dict) else None
        geometric = (isinstance(request, dict) and isinstance(request.get('options'), dict)
                     and request['options'].get('support_mode') == 'geometric')
        if schema == 2 or geometric:
            if schema != 2 or not geometric:
                return ['request/result schema mismatch']
            validation_3d.validate_result(request, result, diagnostics=diagnostics)
            return []
        if schema != 1:
            return ['unknown result schema']
        return validation_ordinary.validate(request, result, diagnostics=diagnostics)
    except (ValueError, ArithmeticError, OverflowError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return [str(exc) or type(exc).__name__]
