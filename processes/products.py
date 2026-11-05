import threading
import os
from time import sleep

# hmpps
from hmpps import Slack
from hmpps import ServiceCatalogue
from hmpps.services.job_log_handling import log_debug, log_info

# local
from includes.utils import get_slack_channel_name_and_id

max_threads = 10


class Services:
  def __init__(self, sc_params, slack_params):
    self.sc = ServiceCatalogue(sc_params)
    self.slack = Slack(slack_params)


# Processes Service Catalogue products
def process_sc_product(product, services):
  sc = services.sc
  slack = services.slack

  log_info(f'Processing product: {product.get("name")}')

  # Empty data dict gets populated along the way,
  # and finally used in PUT request to service catalogue
  data = {}

  # Keep the channel ID field unchanged and store both parts in the name field.
  if p_slack_channel := product.get('slack_channel_id'):
    channel_name_and_id = get_slack_channel_name_and_id(slack, p_slack_channel)
    if product.get('slack_channel_name') != channel_name_and_id:
      data['slack_channel_name'] = channel_name_and_id

  if data:
    # Update product with all results in data dict.
    sc.update(sc.products, product['documentId'], data)


def batch_process_sc_products(services, max_threads=10):
  sc = services.sc
  threads = []

  products = sc.get_all_records(sc.products_get)
  log_info(f'Processing batch of {len(products)} products...')
  for product in products:
    t_repo = threading.Thread(
      target=process_sc_product, args=(product, services), daemon=True
    )

    # Slack rate limits in esoteric ways. Hopefully 10 threads is fine
    # https://api.slack.com/apis/rate-limits#tiers
    while threading.active_count() > (max_threads - 1):
      log_debug(f'Active Threads={threading.active_count()}, Max Threads={max_threads}')
      sleep(5)
    threads.append(t_repo)

    t_repo.start()
    log_info(
      f'Started thread for product {product.get("p_id")} ({product.get("name")})'
    )

  for t in threads:
    t.join()
  return len(products)


def main():
  # service catalogue parameters from environment variables
  sc_params = {
    'url': os.getenv('SERVICE_CATALOGUE_API_ENDPOINT', ''),
    'key': os.getenv('SERVICE_CATALOGUE_API_KEY', ''),
    'filter': os.getenv('SC_FILTER', ''),
  }

  # slack parameters from environment variables
  slack_params = {
    'token': os.getenv('SLACK_BOT_TOKEN'),
  }
  services = Services(sc_params, slack_params)

  log_info('Processing products...')
  qty = batch_process_sc_products(services, max_threads)
  log_info(f'Finished processing {qty} products.')
  return qty


if __name__ == '__main__':
  main()
