from setuptools import setup, find_packages

setup(
    name="cozaik-debugger",
    version="0.1.0",
    description="Debugging framework for distributed time-sensitive applications (Cozaik/TTPython)",
    packages=find_packages(),
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "cozaik-debug=cozaik_debugger.main:main",
        ],
    },
)
