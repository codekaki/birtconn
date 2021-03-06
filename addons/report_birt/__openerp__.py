# -*- coding: utf-8 -*-

{
    'name': 'BIRT Report Adapter',
    'version': '1.0',
    'category': 'Tools',
    'description': """
This module allows users to generate reports designed in Eclipse BIRT
=====================================================================

""",
    'author': 'Codekaki Systems (R49045/14)',
    'website': 'http://codekaki.com',
    'summary': 'BIRT, Report',
    'depends': ['base'],
    'demo': [
        'wizard/report_birt_demo.xml',
    ],
    'data': [
        'wizard/report_birt_view.xml',
        'wizard/report_birt_data.xml',
    ],
    'css': [
        'static/src/css/widgets.css',
    ],
    'js': [
        'static/src/js/widgets.js',
    ],
    'qweb': [
        'static/src/xml/widgets.xml',
    ],
    'images': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
