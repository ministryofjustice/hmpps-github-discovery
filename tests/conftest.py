import sys
import types
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

hmpps_module = types.ModuleType('hmpps')
services_module = types.ModuleType('hmpps.services')
job_log_module = types.ModuleType('hmpps.services.job_log_handling')
utils_module = types.ModuleType('hmpps.utils')
utilities_module = types.ModuleType('hmpps.utils.utilities')
job_log_module.log_debug = lambda *args, **kwargs: None
job_log_module.log_info = lambda *args, **kwargs: None
utilities_module.get_request_proxies = lambda: None

sys.modules.setdefault('hmpps', hmpps_module)
sys.modules.setdefault('hmpps.services', services_module)
sys.modules.setdefault('hmpps.services.job_log_handling', job_log_module)
sys.modules.setdefault('hmpps.utils', utils_module)
sys.modules.setdefault('hmpps.utils.utilities', utilities_module)