import os
import sys

project = 'Logging and Metrics Observability'
copyright = '2025, Andy Nael'
author = 'Andy Nael'
release = '1.0'

extensions = [
    'sphinx_rtd_theme',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

html_theme_options = {
    'collapse_navigation': True,
    'sticky_navigation': True,
    'navigation_depth': 4, 
    'includehidden': True, 
}