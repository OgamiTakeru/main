from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import datetime
import fGeneric as f


# accountID = "101-009-20438763-001"  # デモ    # ★★★
# access_token = '955c62ae4f76351d24369b3aae936b35-91f898f60f4dd3e02d4dd8e62754ac61'    # ★★★
# environment = "practice"  # デモ口座 本番は"live"
#
# api = API(access_token=access_token, environment="practice")
#
# params = {
#   "count": 5,
#   "granularity": "M5"
# }
# r = instruments.InstrumentsCandles(instrument="USD_JPY", params=params)
# res = api.request(r)


def dels(temp):
    del temp['1']
    return temp

def main():
    temp = {"1":1, "2":2}
    print(temp)
    ans = dels(temp)
    print(temp)
    print("ans", ans)

main()