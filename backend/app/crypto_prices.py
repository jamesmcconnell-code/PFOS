"""USD valuation for normalized crypto holdings; quantities remain provider-owned balances."""
from datetime import datetime
import httpx

COINGECKO_IDS={
    'AAVE':'aave','ADA':'cardano','ALGO':'algorand','ATOM':'cosmos','BAL':'balancer','BAT':'basic-attention-token','BCH':'bitcoin-cash','BNT':'bancor','BTC':'bitcoin','CGLD':'celo','COMP':'compound-governance-token','DAI':'dai','DASH':'dash','EOS':'eos','ETC':'ethereum-classic','ETH':'ethereum','ETH2':'ethereum','FIL':'filecoin','GRT':'the-graph','KNC':'kyber-network-crystal','LINK':'chainlink','LRC':'loopring','LTC':'litecoin','MANA':'decentraland','MATIC':'matic-network','MKR':'maker','SHIB':'shiba-inu','SNX':'havven','SOL':'solana','UNI':'uniswap','USDC':'usd-coin','USDT':'tether','WBTC':'wrapped-bitcoin','XLM':'stellar','XRP':'ripple','XTZ':'tezos','YFI':'yearn-finance','ZEC':'zcash','ZRX':'0x'
}
USD_PEGGED={'USD':1.0,'USDC':1.0,'USDT':1.0,'DAI':1.0}

def refresh_usd_values(accounts):
    """Refresh each known crypto account in one public request; retain the last quote on provider failure."""
    symbols={str(account.asset_symbol or '').upper() for account in accounts}
    ids=sorted({COINGECKO_IDS[symbol] for symbol in symbols if symbol in COINGECKO_IDS and symbol not in USD_PEGGED})
    prices={symbol:USD_PEGGED[symbol] for symbol in symbols if symbol in USD_PEGGED}
    if ids:
        try:
            response=httpx.get('https://api.coingecko.com/api/v3/simple/price',params={'ids':','.join(ids),'vs_currencies':'usd'},timeout=8).raise_for_status().json()
            prices.update({symbol:float(response[coin_id]['usd']) for symbol,coin_id in COINGECKO_IDS.items() if coin_id in response and 'usd' in response[coin_id]})
        except (httpx.HTTPError,KeyError,TypeError,ValueError):
            return False
    refreshed=False
    for account in accounts:
        price=prices.get(str(account.asset_symbol or '').upper())
        if price is None: continue
        account.crypto_usd_value=round(float(account.balance)*price,2)
        account.crypto_price_updated_at=datetime.utcnow()
        refreshed=True
    return refreshed
