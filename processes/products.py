import logging
import threading
import os
from time import sleep
from classes.slack import Slack
from classes.service_catalogue import ServiceCatalogue

log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
max_threads = 10


class Services:
  def __init__(self, sc_params, slack_params, log):
    self.sc = ServiceCatalogue(sc_params, log)
    self.slack = Slack(slack_params, log)
    self.log = log


# Processes Service Catalogue products
def process_sc_product(product, services):
  sc = services.sc
  slack = services.slack
  log = services.log

  log.info(f'Processing product: {product["attributes"]["name"]}')

  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}

  # Update Slack Channel name if necessary:
  p_slack_channel_id = product['attributes']['slack_channel_id']
  p_slack_channel_name = product['attributes']['slack_channel_name']
  if p_slack_channel_id != '':
    if slack_channel_name := slack.get_slack_channel_name_by_id(p_slack_channel_id):
      if p_slack_channel_name != slack_channel_name:
        data['slack_channel_name'] = slack_channel_name

  if data:
    # Update product with all results in data dict.
    sc.update(sc.products, product['id'], data)


def batch_process_sc_products(services, max_threads=10):
  sc = services.sc
  log = services.log
  threads = []

  products = sc.get_all_records(sc.products_get)
  log.info(f'Processing batch of {len(products)} products...')
  for product in products:
    t_repo = threading.Thread(
      target=process_sc_product, args=(product, services), daemon=True
    )

    # Slack rate limits in esoteric ways. Hopefully 10 threads is fine
    # https://api.slack.com/apis/rate-limits#tiers
    while threading.active_count() > (max_threads - 1):
      log.debug(f'Active Threads={threading.active_count()}, Max Threads={max_threads}')
      sleep(5)
    threads.append(t_repo)

    t_repo.start()
    log.info(
      f'Started thread for product {product["attributes"]["p_id"]} ({product["attributes"]["name"]})'
    )

  for t in threads:
    t.join()
  return len(products)


def main():
  logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=log_level
  )
  log = logging.getLogger(__name__)

  # service catalogue parameters from environment variables
  sc_params = {
    'sc_api_endpoint': os.getenv('SERVICE_CATALOGUE_API_ENDPOINT'),
    'sc_api_token': os.getenv('SERVICE_CATALOGUE_API_KEY'),
    'sc_filter': os.getenv('SC_FILTER', ''),
  }

  # slack parameters from environment variables
  slack_params = {
    'slack_bot_token': os.getenv('SLACK_BOT_TOKEN'),
  }
  services = Services(sc_params, slack_params, log)

  log.info('Processing products...')
  qty = batch_process_sc_products(services, max_threads)
  log.info(f'Finished processing {qty} products.')
  return qty


if __name__ == '__main__':
  main()
