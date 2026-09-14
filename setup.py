from setuptools import find_packages, setup

setup(
    name="data-lake-service",
    version="0.1.0",
    description="Reusable lake host: HTTP contract, configuration and backend interface",
    packages=find_packages(include=["data_lake_service", "data_lake_service.*"]),
    include_package_data=True,
    package_data={"data_lake_service": ["templates/*.html", "static/css/*.css"]},
    entry_points={
        "console_scripts": ["data-lake=data_lake_service.main:main"],
        # A disposable provider shipped with the host, so a fresh install can serve
        # something without any other distribution. It is a demo, never production data.
        "datalake.backends": ["memory_store=data_lake_service.testing.memory_store:backend"],
    },
    install_requires=["flask>=3.0"],
    python_requires=">=3.10",
)
