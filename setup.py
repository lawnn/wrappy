from pathlib import Path

from setuptools import find_packages, setup


README = Path(__file__).with_name("README.md").read_text(encoding="utf-8")


setup(
    name="wrappy",
    version="0.6.0",
    author="lawn",
    url="https://github.com/lawnn/wrappy.git",
    description="Async helpers for crypto trading bots.",
    long_description=README,
    long_description_content_type="text/markdown",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=[
        "aiohttp",
        "pybotters",
    ],
    extras_require={
        "analytics": [
            "matplotlib",
            "numpy",
            "pandas",
            "polars",
            "pytz",
        ],
        "lighter": [
            "lighter-sdk",
        ],
        "full": [
            "lighter-sdk",
            "matplotlib",
            "numpy",
            "pandas",
            "polars",
            "pytz",
        ],
    },
)
