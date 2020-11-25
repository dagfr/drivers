from naas_drivers.driver import InDriver, OutDriver
import pandas as pd
import requests
import os
from datetime import datetime

 
class Organizations:
    def __init__(self, user_id, api_key):
        self.base_url = os.environ.get(
            "QONTO_API_URL", "http://thirdparty.qonto.eu/v2"
        )
        self.req_headers = {
            "authorization": f'{user_id}:{api_key}'
        }
        self.url = f"{self.base_url}/organizations"
        self.user_id = user_id
        
    def get(self):
        try:
            req = requests.get(
                url=f"{self.url}/{user_id}",
                headers=self.req_headers
            )
            req.raise_for_status()
            items = req.json()['organization']['bank_accounts']
            df = pd.DataFrame.from_records(items)
            
            # Formating CS
            df["date"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            df = df.drop(["slug", "balance_cents", "authorized_balance_cents"], axis=1)
            df.columns = df.columns.str.upper()
            return df
        except requests.HTTPError as err:
            err_code = err.response.status_code
            err_msg = err.response.json()
            to_print = f"{err_code}: {err_msg}"
            print(to_print)

            
class Transactions(Organizations):
    def get_all(self):
        # Get organizations
        df_organisations = self.get()

        # For each bank account, get all transactions
        df_transaction = pd.DataFrame()
        for _, row in df_organisations.iterrows():
            iban = row['IBAN']
            
            # Get transactions
            current_page = "1"
            has_more = True
            while has_more:
                req = requests.get(
                    url=f'{self.base_url}/transactions?current_page={current_page}?per_page=100&iban={iban}',
                    headers=self.req_headers
                )
                items = req.json()
                transactions = items['transactions']
                df = pd.DataFrame.from_records(transactions)
                df['iban'] = iban
                df_transaction = pd.concat([df_transaction, df], axis=0)
                
                # Check if next page exists
                next_page = items["meta"]["next_page"]
                if next_page is None:
                    has_more = False
                else:
                    current_page = str(next_page)
                    
        # Formatting
        to_keep = [
           "iban",
           "settled_at",
           "emitted_at",
           "transaction_id",
           "label",
           "reference",
           "operation_type",
           "side",
           "amount",
           "currency"
           ]
        df_transaction = df_transaction[to_keep].reset_index(drop=True).fillna("Not affected")
        df_transaction.loc[df_transaction['side'] == 'debit', 'amount'] = df_transaction['amount'] * (-1)
        df_transaction.columns = df_transaction.columns.str.upper()
        return df_transaction
    
class Statements(Transactions):
    def detailed(self):
        df = self.get_all()
        df = df.rename(columns={"EMITTED_AT": "DATE"})
        df["DATE"] = pd.to_datetime(df["DATE"], format='%Y-%m-%dT%H:%M:%S.%fZ').dt.strftime("%Y-%m-%d")
        
        # Calc positions
        to_sort = ['IBAN', 'DATE']
        df = df.sort_values(by=to_sort).reset_index(drop=True)
        to_group = ['IBAN']
        df['POSITION'] = df.groupby(to_group, as_index=True).agg({'AMOUNT': 'cumsum'})
        to_keep = [
           "IBAN",
           "DATE",
           "TRANSACTION_ID",
           "LABEL",
           "REFERENCE",
           "OPERATION_TYPE",
           "AMOUNT",
           "POSITION",
           "CURRENCY",
           ]
        df = df[to_keep]
        return df
    
    def aggregated(self):
        df = self.get_all()
        df = df.rename(columns={"EMITTED_AT": "DATE"})
        df["DATE"] = pd.to_datetime(df["DATE"], format='%Y-%m-%dT%H:%M:%S.%fZ').dt.strftime("%Y-%m-%d")
        
        # Aggregation
        to_group = ["IBAN", "DATE", "CURRENCY"]
        df = df.groupby(to_group, as_index=False).agg({"AMOUNT": "sum"})
        
        # Calc positions
        to_sort = ['IBAN', 'DATE']
        df = df.sort_values(by=to_sort).reset_index(drop=True)
        to_group = ['IBAN']
        df['POSITION'] = df.groupby(to_group, as_index=True).agg({'AMOUNT': 'cumsum'})
        to_keep = [
           "IBAN",
           "DATE",
           "AMOUNT",
           "POSITION",
           "CURRENCY",
           ]
        df = df[to_keep]
        return df
    

class Qonto(InDriver):
    user_id = None
    api_token = None

    def connect(self, user_id, api_token):
        # Init thinkific attribute
        self.user_id = user_id
        self.token = api_token
        
        # Init end point
        self.positions = Organizations(self.user_id, self.token)
        self.flows = Transactions(self.user_id, self.token)
        self.statement = Statements(self.user_id, self.token)
        
        # Set connexion to active
        self.connected = True
        return self