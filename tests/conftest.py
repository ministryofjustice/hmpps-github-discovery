import sys
import types
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

hmpps_module = types.ModuleType('hmpps')
services_module = types.ModuleType('hmpps.services')
job_log_module = types.ModuleType('hmpps.services.job_log_handling')


class GithubSession:  # pragma: no cover - stub for import-time compatibility
  pass


class ServiceCatalogue:  # pragma: no cover - stub for import-time compatibility
  pass


class SharePoint:  # pragma: no cover - stub for import-time compatibility
  pass


job_log_module.log_debug = lambda *args, **kwargs: None
job_log_module.log_info = lambda *args, **kwargs: None
job_log_module.log_warning = lambda *args, **kwargs: None
job_log_module.log_error = lambda *args, **kwargs: None
job_log_module.job = types.SimpleNamespace(error_messages=[])

hmpps_module.GithubSession = GithubSession
hmpps_module.ServiceCatalogue = ServiceCatalogue
hmpps_module.SharePoint = SharePoint
hmpps_module.services = services_module
services_module.job_log_handling = job_log_module

sys.modules.setdefault('hmpps', hmpps_module)
sys.modules.setdefault('hmpps.services', services_module)
sys.modules.setdefault('hmpps.services.job_log_handling', job_log_module)
