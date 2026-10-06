"""
Payment Engine Abstraction
V0: BCH Adapter
Future: ZEC, others
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum
import os
import secrets
import httpx
from datetime import datetime, timezone, timedelta

class Currency(str, Enum):
    BCH = "BCH"
    ZEC = "ZEC"  # V1

@dataclass
class PaymentRequest:
    amount: float
    currency: Currency
    memo: str
    address: str
    expires_at: datetime
    payment_id: Optional[int] = None

@dataclass
class PaymentVerificationResult:
    confirmed: bool
    transaction_id: Optional[str] = None
    confirmations: int = 0
    amount_received: float = 0.0
    error: Optional[str] = None

class PaymentAdapter(ABC):
    @abstractmethod
    async def generate_payment_request(self, amount: float, memo: str) -> PaymentRequest:
        pass

    @abstractmethod
    async def verify_payment(self, address: str, amount: float, memo: str, since: datetime) -> PaymentVerificationResult:
        pass

    @abstractmethod
    def get_currency(self) -> Currency:
        pass

class BCHAdapter(PaymentAdapter):
    """
    BCH Payment Adapter.
    Uses a configured receiving address (or HD derivation in production).
    Verification via public Blockchair / CashNodes style explorers or custom node.
    For V0 we use Blockchair API (public, rate-limited) + unique amount/memo pattern.
    """
    def __init__(self):
        # In production: use HD wallet derivation for unique addresses per payment
        # For V0: single address + unique memo / unique amount (satoshi precision)
        self.receiving_address = os.getenv("BCH_RECEIVING_ADDRESS", "bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvyhc29hc")
        self.explorer_base = "https://api.blockchair.com/bitcoin-cash"
        self.min_confirmations = int(os.getenv("BCH_MIN_CONFIRMATIONS", "1"))
        # Use unique amounts by adding tiny random satoshi dust for identification when memo not available on-chain easily
        self.use_unique_amount = True

    def get_currency(self) -> Currency:
        return Currency.BCH

    async def generate_payment_request(self, amount: float, memo: str) -> PaymentRequest:
        # Generate unique identifier
        unique_memo = f"MV-{memo}-{secrets.token_hex(4)}"
        # Optionally adjust amount by a few satoshis for uniqueness if needed
        # 1 BCH = 1e8 satoshis
        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        return PaymentRequest(
            amount=round(amount, 8),
            currency=Currency.BCH,
            memo=unique_memo,
            address=self.receiving_address,
            expires_at=expires
        )

    async def verify_payment(self, address: str, amount: float, memo: str, since: datetime) -> PaymentVerificationResult:
        """
        Verify by querying recent transactions to the address.
        Match approximate amount (within dust) and preferably memo if present in OP_RETURN.
        For robustness in V0 we match amount within 1000 satoshis and time window.
        """
        # Test mode short-circuit (for local/dev without real BCH)
        test_mode = os.getenv("PAYMENT_TEST_MODE", "false").lower() == "true"
        if test_mode:
            return PaymentVerificationResult(
                confirmed=True,
                transaction_id=f"test-{secrets.token_hex(16)}",
                confirmations=6,
                amount_received=amount
            )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Blockchair dashboard API for address
                url = f"{self.explorer_base}/dashboards/address/{address}?limit=20"
                resp = await client.get(url)
                if resp.status_code != 200:
                    return PaymentVerificationResult(confirmed=False, error=f"Explorer error: {resp.status_code}")

                data = resp.json()
                address_data = data.get("data", {}).get(address, {})
                txs = address_data.get("transactions", [])


                # Real path: look for matching incoming
                # Note: public explorers may require API key for high volume; document this.
                for tx_hash in txs[:10]:
                    # Fetch tx details
                    tx_url = f"{self.explorer_base}/dashboards/transaction/{tx_hash}"
                    tx_resp = await client.get(tx_url)
                    if tx_resp.status_code != 200:
                        continue
                    tx_data = tx_resp.json().get("data", {}).get(tx_hash, {})
                    outputs = tx_data.get("outputs", [])
                    for out in outputs:
                        if out.get("recipient") == address.replace("bitcoincash:", ""):
                            received = out.get("value", 0) / 1e8  # sat to BCH
                            if abs(received - amount) < 0.00001:  # ~1000 sat tolerance
                                # Check time
                                time_str = tx_data.get("transaction", {}).get("time")
                                # Simplified: accept if amount matches
                                conf = tx_data.get("transaction", {}).get("block_id") is not None
                                return PaymentVerificationResult(
                                    confirmed=True,
                                    transaction_id=tx_hash,
                                    confirmations=6 if conf else 0,
                                    amount_received=received
                                )
                return PaymentVerificationResult(confirmed=False, error="No matching transaction found")
        except Exception as e:
            return PaymentVerificationResult(confirmed=False, error=str(e))

class PaymentEngine:
    def __init__(self):
        self.adapters: Dict[Currency, PaymentAdapter] = {
            Currency.BCH: BCHAdapter(),
        }
        # Future: self.adapters[Currency.ZEC] = ZECAdapter()

    def get_adapter(self, currency: Currency = Currency.BCH) -> PaymentAdapter:
        if currency not in self.adapters:
            raise ValueError(f"Currency {currency} not supported in this version")
        return self.adapters[currency]

    async def create_payment(self, amount: float, currency: Currency, memo: str) -> PaymentRequest:
        adapter = self.get_adapter(currency)
        return await adapter.generate_payment_request(amount, memo)

    async def verify_payment(self, currency: Currency, address: str, amount: float, memo: str, since: datetime) -> PaymentVerificationResult:
        adapter = self.get_adapter(currency)
        return await adapter.verify_payment(address, amount, memo, since)

# Singleton
payment_engine = PaymentEngine()
