from setuptools import setup, find_packages

setup(
    name='mcd_stitcher',
    version='1.0.0',
    author='Pawan Chaurasia',
    author_email='pchaurasia98@gmail.com',
    description='MCD to Zarr conversion and stitching',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/PawanChaurasia/mcd_stitcher',
    project_urls={
        'Bug Tracker': 'https://github.com/PawanChaurasia/mcd_stitcher/issues',
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    packages=find_packages(),
    python_requires='>=3.10',
    install_requires=[
        'click',
        'numpy',
        'pandas',
        'python_dateutil',
        'xarray',
        'zarr',
        'scikit-image',
        'xmltodict',
        'tifffile'
    ],
    entry_points={
        'console_scripts': [
            'imc2zarr=mcd_stitcher.converter:main',
            'zarr_stitch=mcd_stitcher.stitcher:main',
            'mcd_stitch=mcd_stitcher:main',
            'tiff_subset=mcd_stitcher.tiff_subset:main',
        ],
    },
)
