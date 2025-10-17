from setuptools import setup, find_packages

setup(
    name='wrappy',
    packages=find_packages(),
    version='0.5.0',
    author='lawn',
    url='https://github.com/lawnn/wrappy.git',
    install_requires=['requests', 'asyncio', 'pybotters', 'matplotlib', 'pandas', 'numpy', 'polars', 'pytz']
)
