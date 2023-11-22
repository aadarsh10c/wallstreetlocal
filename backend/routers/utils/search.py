import meilisearch

from dotenv import load_dotenv
from os import getenv
from time import sleep

from .mongo import *

load_dotenv()

# pyright: reportGeneralTypeIssues=false

MEILISEARCH_SERVER_URL = f'http://{getenv("MEILISEARCH_SERVER_URL")}:7700'
MEILISEARCH_MASTER_KEY = getenv("MEILISEARCH_MASTER_KEY")
print("[ Search (Meilisearch) Initializing ] ...")

search = meilisearch.Client(MEILISEARCH_SERVER_URL, MEILISEARCH_MASTER_KEY)
if "companies" not in [index.uid for index in search.get_indexes()["results"]]:
    search.create_index("companies", {"primaryKey": "cik"})
    sleep(3)
    search = meilisearch.Client(MEILISEARCH_SERVER_URL, MEILISEARCH_MASTER_KEY)
companies_index = search.index("companies")
companies_index.update_displayed_attributes(
    [
        "name",
        "cik",
        "tickers",
    ]
)
companies_index.update_searchable_attributes(["name", "tickers", "cik"])
companies_index.update_filterable_attributes(["thirteen_f"])


def search_companies(query, options={}):
    result = companies_index.search(query, options)
    hits = result["hits"]

    return hits


print("[ Search (Meilisearch) Initialized ]")
