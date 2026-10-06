import os
from dataclasses import dataclass

@dataclass
class EconomicConfig:
    # Platform takes a cut of entry fees and/or room rentals
    PLATFORM_ROOM_FEE_PERCENT: float = float(os.getenv("PLATFORM_ROOM_FEE_PERCENT", "10.0"))  # of rental
    PLATFORM_ENTRY_FEE_PERCENT: float = float(os.getenv("PLATFORM_ENTRY_FEE_PERCENT", "5.0"))  # of entry
    HOST_REVENUE_SHARE: float = float(os.getenv("HOST_REVENUE_SHARE", "95.0"))  # remaining to host
    MINIMUM_ROOM_PRICE: float = float(os.getenv("MINIMUM_ROOM_PRICE", "0.0001"))
    # Base rental prices by duration (can be overridden)
    BASE_RENTAL_PER_HOUR: float = float(os.getenv("BASE_RENTAL_PER_HOUR", "0.001"))

economic_config = EconomicConfig()

# Duration options in minutes
DURATION_OPTIONS = [30, 60, 180, 360, 720, 1440, 10080]  # 30m to 7d

# Capacity options
CAPACITY_OPTIONS = [10, 25, 50, 100, 250, 500, 1000]

CATEGORIES = [
    "Business", "Football", "Gaming", "Crypto", "Culture", "Music",
    "Entertainment", "Dating", "Education", "Technology", "Local",
    "Politics", "Religion", "Memes", "Other"
]
