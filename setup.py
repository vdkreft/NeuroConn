from setuptools import setup, find_packages

with open('README.md', 'r') as f:
    long_description = f.read()

setup(
    name='NeuroConn',
    version='0.1.0a5',
    description='A BIDS toolbox for connectivity & gradient analyses.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Victoria Shevchenko',
    author_email='shevchenko682@gmail.com',
    python_requires='>=3.6',
    packages=find_packages(),
    url='https://github.com/victoris93/NeuroConn',  # Added comma here
    install_requires=[
        'nilearn',
        'numpy',
        'pandas',
        'scikit-learn',
        'nibabel',
        'brainspace',
        'gdown',
        'fmriprep-docker', 
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    keywords='fmriprep, BIDS, connectivity, gradients, dispersion',
)