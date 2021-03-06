# -*- encoding: utf-8 -*-

from collections import OrderedDict
from datetime import datetime, date, time
from lxml import etree
from openerp import netsvc, tools, SUPERUSER_ID
from openerp.osv import fields, osv
from openerp.report.interface import report_int
from openerp.tools.translate import _
import openerp.pooler as pooler
import os
import re
import requests
import simplejson as json


def get_report_api(cr, uid, pool, context=None):
    ir_config_parameter = pool.get("ir.config_parameter")
    api = ir_config_parameter.get_param(cr, uid, "birtconn.api", context=context)
    if not api:
        # fallback, look in to config file
        api = tools.config.get_misc('birtconn', 'api')
    if not api:
        raise ValueError("System property 'birtconn.api' is not defined.")
    return os.path.join(api, 'report')


def serialize(obj):
    if isinstance(obj, datetime):
        return datetime.strftime(obj, tools.DEFAULT_SERVER_DATETIME_FORMAT)
    if isinstance(obj, date):
        return datetime.strftime(obj, tools.DEFAULT_SERVER_DATE_FORMAT)
    if isinstance(obj, time):
        return datetime.strftime(obj, tools.DEFAULT_SERVER_TIME_FORMAT)
    raise TypeError(obj)


class report_birt_report_wizard(osv.osv_memory):
    _name = 'report_birt.report_wizard'
    _description = 'BIRT Report Wizard'

    _columns = {
        '__report_name': fields.char(size=64, string="Report Name"),
        '__values': fields.text(string="Values"),
    }

    def _report_get(self, cr, uid, context=None):
        if 'report_name' in context:
            report_obj = self.pool.get('ir.actions.report.xml')
            found = report_obj.search(cr, uid, [('report_name', '=', context['report_name'])])
            if found:
                report_id = found[0]
                report = report_obj.read(cr, uid, report_id, ['report_file'])

                report_api = get_report_api(cr, uid, self.pool, context)

                r = requests.get('%s?report_file=%s' % (report_api, report['report_file']))
                return r.json()
        return {}

    def default_get_recursively(self, cr, uid, fields_list, parameters, context=None):
        res = {}
        for param in parameters:
            name = param['name']
            if name.startswith('__'):
                key = name[2:]
                if key in context:
                    res[name] = context[key]
            else:
                ptype = param['type'].split('/')
                if ptype[0] == "scalar":
                    fieldType = param['fieldType']
                    if fieldType == 'time':
                        # 'time' is not supported by OpenERP by default, but datetime is. So, we treat time as datetime field
                        # and use our custom timepicker widget.
                        fieldType = 'datetime'

                    if fieldType == 'char' and ptype[1] == 'multi-value':
                        val = param['defaultValue']
                    elif fieldType in ['boolean']:
                        # unfortunately, boolean field setter converts False to 'False', a truthful value.
                        # so we override it with the raw value which is in the correct type.
                        val = param['defaultValue']
                    else:
                        conv = getattr(fields, fieldType)(string=param['promptText'])._symbol_set[1]
                        v1 = param['defaultValue']
                        if isinstance(v1, (list, tuple)):
                            val = [conv(v) for v in v1]
                        else:
                            val = conv(v1)
                    res[name] = val
                elif ptype[0] == "group":
                    parameters_g = param['parameters']
                    res_g = self.default_get_recursively(cr, uid, fields_list, parameters_g, context)
                    res.update(res_g)
        return res

    def default_get(self, cr, uid, fields_list, context=None):
        res = {}
        parameters = self._report_get(cr, uid, context)
        return self.default_get_recursively(cr, uid, fields_list, parameters, context)

    def fields_get_meta(self, cr, uid, param, context, res, fgroup=None):
        name = param['name']
        meta = {}
        ptype = param['type'].split('/')

        if ptype[0] == 'group':
            for p in param['parameters']:
                self.fields_get_meta(cr, uid, p, context, res, {'name': param['name'], 'string': param['promptText']})

        if ptype[0] == 'scalar':
            meta['type'] = param['fieldType']
            meta['context'] = {
                'scalar': ptype[1]
            }

            # refer to field_to_dict if you don't understand why
            if 'selection' in param and param['selection']:
                meta['selection'] = param['selection']
                meta['type'] = 'selection'  # override default input type

            meta['string'] = param['promptText']
            meta['required'] = param['required']
            meta['invisible'] = param['hidden']
            meta['help'] = param['helpText']

            meta['context']['type'] = param['fieldType']  # actual data type
            if fgroup:
                meta['context']['fgroup'] = fgroup
            res[name] = meta


    def fields_get(self, cr, uid, fields_list=None, context=None, write_access=True):
        context = context or {}

        res = super(report_birt_report_wizard, self).fields_get(cr, uid, fields_list, context, write_access)
        for f in self._columns:
            for attr in ['invisible', 'readonly']:
                res[f][attr] = True

        parameters = self._report_get(cr, uid, context)
        for param in parameters:
            self.fields_get_meta(cr, uid, param, context, res)

        def order_by(parameters):
            def _wrap(name):
                for i, param in enumerate(parameters):
                    ptype = param['type'].split('/')
                    if ptype[0] == 'group':
                        j = order_by(param['parameters'])(name)
                        if j != -1:
                            return (i * 10) + j
                    elif ptype[0] == 'scalar' and param['name'] == name:
                            return (i * 10)
                return -1
            return _wrap

        if parameters:
            res_cur = res
            res_new = OrderedDict()

            # What we are trying to achieve here is to order fields by the order they (parameters) are defined in the rptdesign. Because
            # a parameter may be a group parameter, we will also inspect the group by loop check its content.
            for k in sorted(res, cmp, key=order_by(parameters)):
                res_new[k] = res_cur[k]
            res = res_new

        # if no fields is specified, return all
        if not fields_list:
            return res
        else:
            # return only what is requested
            return dict(filter(lambda (k, v): k in fields_list, a.items()))


    def create(self, cr, uid, vals, context=None):
        # 'vals' contains all field/value pairs, including report_name, parameters and values.
        # But we don't have all the columns since they are dynamically generated
        # based on report's parameters.
        values = dict(filter(lambda (x, y): x not in ['__report_name', '__values'], vals.items()))
        values = json.dumps(values)

        report_name = context['report_name']
        vals = {
            '__report_name': report_name,
            '__values': values,
        }
        return super(report_birt_report_wizard, self).create(cr, uid, vals, context)

    def _get_lang_dict(self, cr, uid, context):
        lang_obj = self.pool.get('res.lang')
        lang = context and context.get('lang', 'en_US') or 'en_US'
        lang_ids = lang_obj.search(cr, uid, [('code','=',lang)])
        if not lang_ids:
            lang_ids = lang_obj.search(cr, uid, [('code','=','en_US')])
        lang_obj = lang_obj.browse(cr, uid, lang_ids[0])
        return {'date_format': lang_obj.date_format, 'time_format': lang_obj.time_format}

    def print_report(self, cr, uid, ids, context=None):
        lang_dict = self._get_lang_dict(cr, uid, context)
        values = self.read(cr, uid, ids[0], ['__values'], context=context)['__values']
        values = json.loads(values)
        def conv(v1):
            # cast value to the correct type with OpenERP's internal setter
            v2 = getattr(fields, t1)(**descriptor)._symbol_set[1](v1)

            # but sometimes, we have to override value to a different type because
            # OpenERP is slightly different/not supporting param type BIRT expects.
            if t1 == 'char' and s1 == 'multi-value':
                # our multivalue checkbox widget that sends values in an array
                if not isinstance(v1, (list, tuple)):
                    v1 = [v1]
                v2 = v1
            elif t1 == 'time':
                # NOTE: time is represented as datetime field with custom timepicker widget
                time_format = lang_dict['time_format']
                cc = time_format.count(':') + 1
                v2 = datetime.strptime(':'.join(v1.split(':')[:cc]), time_format)
                v2 = getattr(fields, 'datetime')(**descriptor)._symbol_set[1](v1)
            return v2

        report_name = context['report_name']
        fg = self.fields_get(cr, uid, context={'report_name': report_name})
        for (name, descriptor) in fg.items():
            if name not in self._columns:
                s1 = descriptor['context']['scalar']
                t1 = descriptor['context']['type']
                v1 = values[name]

                if isinstance(v1, (list, tuple)):
                    v2 = [conv(v) for v in v1]
                else:
                    v2 = conv(v1)
                values[name] = v2
        return {
            'type': 'ir.actions.report.xml',
            'report_name': context['report_name'],
            'datas': values,
        }

    def fields_view_get(self, cr, uid, view_id=None, view_type='form', context=None, toolbar=False, submenu=False):
        res = super(report_birt_report_wizard, self).fields_view_get(cr, uid, view_id, view_type, context, toolbar, submenu)
        if view_type == 'search':
            return res

        xarch = etree.XML(res['arch'])
        group_values = xarch.xpath('//group[@name="__values"]')[0]

        for field, descriptor in self.fields_get(cr, uid, context=context).iteritems():
            if 'context' in descriptor and 'fgroup' in descriptor['context']:
                fgroup = descriptor['context']['fgroup']
                elg = xarch.xpath('//group[@name="%(name)s"][@string="%(string)s"]' % fgroup)
                if elg:
                    _g = elg[0]
                else:
                    _g = etree.SubElement(group_values, 'group', name=fgroup['name'], string=fgroup['string'], colspan="2")
                el = etree.SubElement(_g, 'field', name=field)
            else:
                el = etree.SubElement(group_values, 'field', name=field)

            if field == 'time':
                # use custom timepicker widget
                el.set('widget', 'timepicker')

            if 'multi-value' == descriptor.get('context', {}).get('scalar'):
                # use custom multiselect widget
                el.set('widget', 'multiselect')

        xarch, xfields = self._view_look_dom_arch(cr, uid, xarch, view_id, context=context)
        res['fields'] = xfields
        res['arch'] = xarch
        return res

report_birt_report_wizard()


class report_birt(report_int):
    def __init__(self, name, table, reportxml_id):
        super(report_birt, self).__init__(name)
        self.table = table
        self.reportxml_id = reportxml_id

    def create(self, cr, uid, ids, vals, context):
        pool = pooler.get_pool(cr.dbname)
        pool_reportxml = pool.get('ir.actions.report.xml')
        reportxml = pool_reportxml.browse(cr, uid, self.reportxml_id)
        headers = {'Content-type': 'application/json', 'Accept': 'application/octet-stream'}

        for k, v in context.items():
            akey = '__%s' % k
            if akey not in vals:
                vals[akey] = v

        data = {
            'reportFile': reportxml.report_file,
            '__values': vals,
            }

        report_api = get_report_api(cr, uid, pool, context)

        req = requests.post(report_api, data=json.dumps(data, default=serialize), headers=headers)
        ext = re.search(r'filename=.+\.(.+);?', req.headers.get('content-disposition')).group(1)
        return (req.content, ext)


class registry(osv.osv):
    _inherit = 'ir.actions.report.xml'

    def register(self, cr, uid, ids, context=None):
        svccls = netsvc.Service
        if ids:
            cr.execute("SELECT id, model, report_name FROM ir_act_report_xml WHERE id in (%s)" % (', '.join([str(id) for id in ids]),))
            result = cr.dictfetchall()
            for r in result:
                name = 'report.' + r['report_name']
                svccls.remove(name)
                report_birt(name, r['model'], r['id'])

    def register_all(self, cr):
        cr.execute("SELECT id FROM ir_act_report_xml WHERE report_type = 'birt' ORDER BY id")
        ids = [row['id'] for row in cr.dictfetchall()]
        self.register(cr, SUPERUSER_ID, ids)

registry()
