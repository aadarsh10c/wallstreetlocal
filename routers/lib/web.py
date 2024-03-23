from bs4 import BeautifulSoup
from datetime import datetime
from xml.etree import ElementTree

import lxml
import cchardet
import logging

from . import database
from . import api
from . import analysis


logging.info("[ Data Initializing ] ...")

parser = "lxml"


# def process_name(cusip, name, cik):
#     msg = f"Querying Stock\n"
#     found_stock = database.find_stock("cusip", cusip)

#     if found_stock == None:
#         try:
#             data = cusip_request(cusip, cik)
#             result = data["result"][0]
#             ticker = data["symbol"]

#             stock = process_stock(ticker, cusip, cik)

#             if stock:
#                 ticker = stock["ticker"]
#                 name = stock["name"]
#                 msg += f"Success, Added Stock"
#             else:a
#                 name = result["description"]
#                 stock = {
#                     "name": name,
#                     "ticker": ticker,
#                     "cusip": cusip,
#                     "update": False,
#                 }
#                 msg += f"Failed, No Query Data"

#             database.add_stock(stock)
#             database.add_log(cik, msg, name, cusip)

#             return ticker, name
#         except Exception:
#             stock = {"name": name, "ticker": "NA", "cusip": cusip}
#             stock["update"] = False

#             database.add_stock(stock)
#             msg += f"Failed, Unknown Error"

#             database.add_log(cik, msg, name, cusip)
#             return "NA", name
#     else:
#         name = found_stock["name"]
#         msg += f"Success, Found Stock"

#         database.add_log(cik, msg, name, cusip)
#         return found_stock["ticker"], found_stock["name"]


def process_names(stocks, cik):

    cusip_list = list(map(lambda s: s["cusip"], stocks))
    cursor = database.find_stocks("cusip", {"$in": cusip_list})

    global_stocks = {}
    found_stocks = {}
    skip = []

    for found_stock in cursor:
        cusip = found_stock["cusip"]
        found_stocks[cusip] = found_stock

    for stock in stocks:
        cusip = stock["cusip"]
        name = stock["name"]
        msg = f"Querying Stock\n"

        found_stock = found_stocks.get(cusip)
        if found_stock:
            ticker = found_stock["ticker"]
            name = found_stock["name"]
            msg += f"Success, Found Stock"
            global_stocks[cusip] = {
                "name": name,
                "ticker": ticker,
                "cusip": cusip,
                "update": found_stock["update"],
            }
            database.add_log(cik, msg, name, cusip)

        else:
            try:
                result = api.stock_request(cusip, cik, name)
                ticker = result["ticker"]
                name = result["name"]

                stock = process_stock(ticker, cusip, name, cik)

                if stock:
                    ticker = stock["ticker"]
                    name = stock["name"]
                    msg += f"Success, Added Stock"
                else:
                    name = result["name"]
                    stock = {
                        "name": name,
                        "ticker": ticker,
                        "cusip": cusip,
                        "update": False,
                    }
                    msg += f"Failed, No Query Data"

                database.add_stock(stock)
                database.add_log(cik, msg, name, cusip)

                global_stocks[cusip] = stock
                database.add_log(cik, msg, name, cusip)
            except Exception:
                if cusip in skip:
                    continue

                stock = {"name": name, "ticker": "NA", "cusip": cusip, "update": False}

                database.add_stock(stock)
                skip.append(cusip)
                global_stocks[cusip] = stock

                msg += f"Failed, No Query Data"
                database.add_log(cik, msg, name, cusip)

    return global_stocks


def process_filings(data):
    data_filings = data["filings"]["recent"]
    filings = {}
    for i, form in enumerate(data_filings["form"]):
        if "13F-HR" not in form:
            continue

        access_number = data_filings["accessionNumber"][i]
        filing = {
            # "form": data_filings["form"][i],
            "access_number": data_filings["accessionNumber"][i],
            "filing_date": analysis.convert_date(data_filings["filingDate"][i]),
            "report_date": analysis.convert_date(data_filings["reportDate"][i]),
            "document": data_filings["primaryDocument"][i],
            "description": data_filings["primaryDocDescription"][i],
        }
        filings[access_number] = filing

    last_report = "NA"
    first_report = "NA"
    for i, form in enumerate(data_filings["form"]):
        if form == "13F-HR":
            if last_report == "NA":
                last_report = data_filings["accessionNumber"][i]

            first_report = data_filings["accessionNumber"][i]

    return filings, last_report, first_report


def check_new(cik):
    data = api.sec_filer_search(cik)
    recent_filings = data["filings"]["recent"]

    document_reports = []
    for i, form in enumerate(recent_filings["form"]):
        if "13F-HR" == form:
            report = recent_filings["reportDate"][i]
            report = analysis.convert_date(report)
            access = recent_filings["accessionNumber"][i]
            document_reports.append({"report": report, "access": access})
    document_reports = sorted(document_reports, key=lambda d: d["report"])

    latest_report = document_reports[-1]
    latest_date = latest_report["report"]

    filer = database.find_filer(
        cik, {"filings": 1, "last_report": 1}
    )  # Inefficient because I cannot figure out how to retrieve only the report date attribute, even though it seems like a simple operation
    filings = filer["filings"]
    last_report = filer["last_report"]
    queried_report = filings[last_report]["report_date"]

    if latest_date > queried_report:
        latest_access = latest_report["access"]
        return True, latest_access
    else:
        return False, None


def sort_rows(row_one, row_two):
    for i, (lineOne, lineTwo) in enumerate(
        zip(row_one.find_all("td"), row_two.find_all("td"))
    ):
        if lineTwo.text == "NAME OF ISSUER":
            nameColumn = i
        elif lineTwo.text == "TITLE OF CLASS":
            classColumn = i
        elif lineTwo.text == "CUSIP":
            cusipColumn = i
        elif lineOne.text == "VALUE":
            valueColumn = i
            if lineTwo.text == "(x$1000)":
                multiplier = 1000
            else:
                multiplier = 1
        elif lineTwo.text == "PRN AMT":
            shrsColumn = i
    return nameColumn, classColumn, cusipColumn, valueColumn, shrsColumn, multiplier


def process_keys(tickers, name, cik):
    if tickers == []:
        try:
            stock_info = api.stock_request(name, cik)
        except (KeyError, IndexError, LookupError) as e:
            logging.info(f"Failed to get Name Data {name}\n{e}\n")
            stock_info = {}
    else:
        for ticker in tickers:
            try:
                stock_info = api.ticker_request("OVERVIEW", ticker, cik)
                name = stock_info["Name"]
                break
            except Exception as e:
                stock_info = {}
                logging.error(e)
    return name, stock_info  # type: ignore


def initalize_filer(cik, sec_data):
    company = {
        "name": sec_data["name"],
        "cik": cik,
    }
    start = datetime.now().timestamp()
    stamp = {
        **company,
        "logs": [],
        "status": 4,
        "time": {
            "remaining": 0,
            "elapsed": 0,
            "required": 0,
        },
        "start": start,
    }

    database.create_log(stamp)
    database.add_filer(company)
    company = process_filer(sec_data, cik)

    stamp = {"name": company["name"], "start": start}
    database.edit_log(cik, stamp)
    database.edit_filer({"cik": cik}, {"$set": company})

    return company, stamp


redundant_keys = ["name", "cik", "symbol"]


def process_filer(data, cik):
    filings, last_report, first_report = process_filings(data)
    time = (datetime.now()).timestamp()

    name = data["name"]
    tickers = data["tickers"]
    name, info = process_keys(tickers, name, cik)

    extra_data = analysis.convert_underscore(info, {})
    for rk in redundant_keys:
        extra_data.pop(rk, None)

    company = {
        "name": name,
        "cik": cik,
        "tickers": tickers,
        "updated": time,
        "exchanges": data["exchanges"],
        "filings": filings,
        "stocks": [],
        "first_report": first_report,
        "last_report": last_report,
        "financials": extra_data,
    }

    return company


def process_filer_newest(company):
    cik = company["cik"]
    newest_data = api.sec_filer_search(cik)
    filings, last_report = process_filings(newest_data)  # type: ignore

    return filings, last_report


def process_stock(ticker, cusip, name, cik):
    try:
        stock_info = api.ticker_request("OVERVIEW", ticker, cik)
        stock_price = (api.ticker_request("GLOBAL_QUOTE", ticker, cik))["Global Quote"]
    except Exception as e:
        logging.error(e)
        return None

    if stock_info == {} and stock_price == {}:
        return None

    price = stock_price.get("05. price")
    for key in stock_info.keys():
        field = stock_info[key]
        if field == None:
            stock_info[key] = "NA"
    for key in stock_price.keys():
        field = stock_price[key]
        if field == None:
            stock_price[key] = "NA"

    financials = analysis.convert_underscore(stock_info)
    quote = {}
    for key in stock_price:
        new_key = key[4:].replace(" ", "_")
        quote[new_key] = stock_price[key]

    info = {
        "name": stock_info.get("Name", name),
        "ticker": ticker,
        "cik": stock_info.get("CIK", "NA"),
        "cusip": cusip,
        "sector": stock_info.get("Sector", "NA"),
        "industry": stock_info.get("Industry", "NA"),
        "price": "NA" if price == None else float(price),
        "time": (datetime.now()).timestamp(),
        "financials": financials,
        "quote": quote,
        "update": True,
    }

    return info


def process_count_stocks(data, cik):
    index_soup = BeautifulSoup(data, parser)
    rows = index_soup.find_all("tr")
    directory = None
    for row in rows:
        # The most genius code ever written
        info_row = any(
            [
                (
                    True
                    if any(
                        [
                            True if d in table_key and d and d != " " else False
                            for d in [b.text.strip() for b in row]
                        ]
                    )
                    else False
                )
                for table_key in info_table_key
            ]
        )
        if info_row:
            link = row.find("a")
            directory = link["href"]
            break
    if directory == None:
        return 0

    data = api.sec_directory_search(directory, cik)
    stock_soup = BeautifulSoup(data, parser)
    stock_table = stock_soup.find_all("table")[3]
    stock_fields = stock_table.find_all("tr")[1:3]
    stock_rows = stock_table.find_all("tr")[3:]

    (
        _,
        _,
        cusipColumn,
        _,
        _,
        _,
    ) = sort_rows(stock_fields[0], stock_fields[1])

    stock_count = 0
    local_stocks = []
    for row in stock_rows:
        columns = row.find_all("td")
        stock_cusip = columns[cusipColumn].text

        if stock_cusip in local_stocks:
            continue
        else:
            local_stocks.append(stock_cusip)
            stock_count += 1


def scrape_html(cik, filing, directory):

    data = api.sec_directory_search(directory, cik)
    stock_soup = BeautifulSoup(data, parser)
    stock_table = stock_soup.find_all("table")[3]
    stock_fields = stock_table.find_all("tr")[1:3]
    stock_rows = stock_table.find_all("tr")[3:]

    (
        nameColumn,
        classColumn,
        cusipColumn,
        valueColumn,
        shrsColumn,
        multiplier,
    ) = sort_rows(stock_fields[0], stock_fields[1])

    row_stocks = {}
    report_date = filing["report_date"]
    access_number = filing["access_number"]

    for row in stock_rows:
        columns = row.find_all("td")

        stock_name = columns[nameColumn].text
        stock_value = float(columns[valueColumn].text.replace(",", "")) * multiplier
        stock_shrs_amt = float(columns[shrsColumn].text.replace(",", ""))
        stock_class = columns[classColumn].text
        stock_cusip = columns[cusipColumn].text

        row_stock = row_stocks.get(stock_cusip)

        if row_stock == None:
            new_stock = {
                "name": stock_name,
                "ticker": "NA",
                "class": stock_class,
                "market_value": stock_value,
                "shares_held": stock_shrs_amt,
                "cusip": stock_cusip,
                "date": report_date,
                "access_number": access_number,
            }
        else:
            new_stock = row_stock
            new_stock["market_value"] = row_stock["market_value"] + stock_value
            new_stock["shares_held"] = row_stock["shares_held"] + stock_shrs_amt

        row_stocks[stock_cusip] = new_stock
        yield new_stock


def scrape_xml(cik, filing, directory):

    data = api.sec_directory_search(directory, cik)
    stock_soup = BeautifulSoup(data, parser)

    print(stock_soup)


info_table_key = ["INFORMATION TABLE"]


def scrape_stocks(cik, data, filing):
    index_soup = BeautifulSoup(data, parser)
    rows = index_soup.find_all("tr")
    directory = {"link": None, "type": None}
    for row in rows:
        items = list(map(lambda b: b.text.strip(), row))
        if any(item in items for item in info_table_key):
            link = row.find("a")
            href = link["href"]

            is_xml = True if href.endswith(".xml") else False
            is_html = True if "xslForm" in href else False
            is_txt = False

            directory_type = directory["type"]
            if is_xml and is_html == False and True == False:
                directory["type"] = "xml"
                directory["link"] = href
            elif is_xml and is_html and directory_type != "xml":
                directory["type"] = "html"
                directory["link"] = href
            elif is_txt and directory_type != "xml" and directory_type != "html":
                directory["type"] = "txt"
                directory["link"] = href

    link = directory["link"]
    form = directory["type"]
    if not link:
        filing_stocks = {}
        return filing_stocks

    if form == "xml" or False:
        scrape_document = scrape_xml
    if form == "html":
        scrape_document = scrape_html
    elif form == "txt":
        scrape_document = scrape_txt

    update_list = [new_stock for new_stock in scrape_document(cik, filing, link)]
    updated_stocks = process_names(update_list, cik)

    filing_stocks = {}
    for new_stock in update_list:
        stock_cusip = new_stock["cusip"]
        updated_stock = updated_stocks[stock_cusip]

        updated_stock.pop("_id", None)
        new_stock.update(updated_stocks[stock_cusip])

        filing_stocks[stock_cusip] = new_stock

    return filing_stocks


def process_stocks(cik, filings):
    filings_list = sorted(
        [filings[an] for an in filings], key=lambda d: d["report_date"]
    )
    for document in filings_list:
        access_number = document["access_number"]
        data = api.sec_stock_search(cik=cik, access_number=access_number)
        try:
            new_stocks = scrape_stocks(cik=cik, data=data, filing=document)
            yield access_number, new_stocks
        except Exception as e:
            logging.info(f"\nError Updating Stocks\n{e}\n--------------------------\n")
            continue


def query_stocks(found_stocks):
    for found_stock in found_stocks:
        if found_stock == None:
            continue

        ticker = found_stock.get("ticker")
        time = datetime.now().timestamp()
        last_updated = found_stock.get("updated")

        if last_updated != None:
            if (time - last_updated) < (60 * 60 * 24 * 3):
                continue

        try:
            price_info = api.ticker_request("GLOBAL_QUOTE", ticker, "")
            global_quote = price_info["Global Quote"]
            price = global_quote["05. price"]
        except Exception as e:
            logging.error(e)
            continue

        database.edit_stock(
            {"ticker": ticker},
            {"$set": {"updated": time, "recent_price": price, "quote": global_quote}},
        )


def estimate_time(filings, cik):
    stock_count = 0
    for access_number in filings:
        try:
            data = api.sec_stock_search(cik=cik, access_number=access_number)
            new_count = process_count_stocks(data, cik)
            stock_count += new_count  # type: ignore
        except Exception as e:
            logging.info(f"\nError Counting Stocks\n{e}\n--------------------------\n")
            continue

    remaining = analysis.time_remaining(stock_count)

    return remaining


def estimate_time_newest(cik):
    filer = database.find_filer(cik, {"last_report": 1})
    if filer == None:
        return
    last_report = filer["last_report"]

    api.sec_filer_search(cik)

    try:
        data = api.sec_stock_search(cik=cik, access_number=last_report)
        stock_count = process_count_stocks(data, cik)
    except Exception as e:
        logging.info(f"\nError Counting Stocks\n{e}\n--------------------------\n")
        raise

    log = database.find_log(cik, {"status": 1})
    status = log["status"] if log else 4

    remaining = analysis.time_remaining(stock_count)
    database.edit_log(
        cik, {"status": 3 if status > 3 else status, "time.required": remaining}
    )

    return remaining


logging.info("[ Data Initialized ]")
