import logging

class Jobs:
  def __init__(self):
    self.error_messages = []
    self.name = None
  logging.basicConfig(format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level='INFO')
  log = logging.getLogger(__name__)

# Create a global shared instance
job = Jobs()

def log_error(error_message: str):
  job.error_messages.append(error_message)
  job.log.error(f"{error_message}")

def log_critical(error_message: str):
  job.error_messages.append(error_message)
  job.log.critical(f"{error_message}")