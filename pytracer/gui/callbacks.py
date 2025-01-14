import json
import plotly.express as px
import astroid
import dash
import plotly.graph_objs as go
import os
import numpy as np
import plotly.colors as pcolors
import time
from flask_caching import Cache
import dash_ace
from pytracer.gui.app import app
import pytracer.gui.core as pgc
import threading
import random

lock = threading.Lock()

TIMEOUT = 60

cache = Cache(app.server, config={
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': 'cache-directory'
})


@app.callback(
    dash.dependencies.Output("info-table", "data"),
    dash.dependencies.Input("output-clientsid", "loading_state"))
def init_info_table(loading_state):
    header = pgc.get_data().get_header()
    return header


@ app.callback(
    dash.dependencies.Output("data-choosen-txt", "children"),
    [dash.dependencies.Input("info-table", "selected_rows"),
     dash.dependencies.Input("info-table", "data")])
# @cache.memoize(timeout=TIMEOUT)
def update_table_active_cell(selected_rows, data):
    rows = pgc.get_active_row(selected_rows, data)
    rows_str = [
        f"module: {d['module']}, function: {d['function']}" for d in rows]
    msg = f"Selected rows:\n {os.linesep.join(rows_str)}"
    return msg


@app.callback(
    dash.dependencies.Output('color-heatmap', 'options'),
    dash.dependencies.Input('color-heatmap-style', 'value'),
    prevent_initial_call=True)
# @cache.memoize(timeout=TIMEOUT)
def fill_heatmap_color(color_style):
    if color_style is None:
        return []
    style = getattr(px.colors, color_style)
    available_colors = px.colors.named_colorscales()

    colors = []
    for attr in dir(style):
        if "_r" in attr:
            attr_lower = attr.replace('_r', '').lower()
        else:
            attr_lower = attr.lower()
        if attr_lower in available_colors:
            colors.append({'label': attr, 'value': attr})
    return colors

# @cache.memoize(timeout=TIMEOUT)


def str_to_utf8(string):
    return bytes(string, 'utf-8')

# @cache.memoize(timeout=TIMEOUT)


def utf8_to_str(utf8):
    return utf8.decode('utf-8')


def frame_args(duration):
    return {
        "frame": {"duration": duration},
        "mode": "immediate",
        "fromcurrent": True,
        "transition": {"duration": duration, "easing": "linear"},
    }


def extra_value_to_heatmap(extra_value):
    with lock:
        _ndarray = extra_value.read()
    ndim = _ndarray.ndim

    if ndim == 1:
        _ndarray = _ndarray.reshape(_ndarray.shape+(1,))
    if ndim == 3:
        _row = _ndarray.shape[0]
        _col = _ndarray.shape[1] * _ndarray.shape[2]
        _ndarray = _ndarray.reshape((_row, _col))
    if ndim > 3:
        _row = _ndarray.shape[0]
        _col = np.prod(_ndarray.shape[1:])
        _ndarray = _ndarray.reshape((_row, _col))

    _row, _col = _ndarray.shape
    _x = list(range(_row))
    _y = list(range(_col))

    return _x, _y, _ndarray


def extra_value_to_graph(extra_value):
    with lock:
        _ndarray = extra_value.read()
        if _ndarray.ndim == 2:
            if _ndarray.shape[0] == 1 or _ndarray.shape[1] == 1:
                return _ndarray.ravel()
    return _ndarray


def get_heatmap(x, y, z, zmin=None, zmax=None):
    if z is None:
        return go.Figure()
    heatmap = go.Figure(data=go.Heatmap(x=x,
                                        y=y,
                                        z=z,
                                        zmin=None,
                                        zmax=None,
                                        coloraxis='coloraxis'))
    heatmap.update_layout(width=700, height=700)
    return heatmap


def read_extra_value(x, info, mode):
    try:
        with lock:
            extra_value = pgc.data.get_extra_value(info['module'],
                                                   info['function'],
                                                   info['label'],
                                                   info['arg'],
                                                   x,
                                                   mode)

    except KeyError:
        extra_value = None
    return extra_value


def get_graph_complex_1D(z):
    z_real = go.Scatter(y=z.real, name=r'$ \Re $')
    z_imag = go.Scatter(y=z.imag, name=r'$ \Im $')
    return go.Figure(data=[z_real, z_imag])


def get_graph_complex(z):
    if z.ndim == 1:
        return get_graph_complex_1D(z)
    else:
        return go.Figure()


def get_scatter_complex_1D(z):
    z_real = go.Scatter(y=z.real, name=r'$ \Re $', mode='markers')
    z_imag = go.Scatter(y=z.imag, name=r'$ \Im $', mode='markers')
    return go.Figure(data=[z_real, z_imag])


def get_scatter_complex(z):
    if z.ndim == 1:
        return get_scatter_complex_1D(z)
    else:
        return go.Figure()


def get_graph_real_1D(z):
    return go.Figure(data=[go.Scatter(y=z)])


def get_scatter_real_1D(z):
    return go.Figure(data=[go.Scatter(y=z, mode='markers')])


def get_graph_real(z):
    if z.ndim == 1:
        return get_graph_real_1D(z)
    else:
        return go.Figure()


def get_scatter_real(z):
    if z.ndim == 1:
        return get_scatter_real_1D(z)
    else:
        return go.Figure()


def get_graph_figure(figure_real, extra_value):
    z = extra_value_to_graph(extra_value)

    if np.iscomplexobj(z):
        return get_graph_complex(z)
    else:
        return get_graph_real(z)


def get_scatter_figure(figure_real, extra_value):
    z = extra_value_to_graph(extra_value)

    if np.iscomplexobj(z):
        return get_scatter_complex(z)
    else:
        return get_scatter_real(z)


def get_heatmap_figure(figure_real, figure_imag, extra_value, zscale, mode, min_scale, max_scale, color):
    _x, _y, _z = extra_value_to_heatmap(extra_value)

    if np.iscomplexobj(_z):
        _z_real = _z.real
        _z_imag = _z.imag
    else:
        _z_real = _z
        _z_imag = None

    if zscale == 'log2':
        _z_real = np.log2(np.abs(_z_real))
        if _z_imag is not None:
            _z_imag = np.log2(np.abs(_z_imag))

    if zscale == 'log10':
        _z_real = np.log10(np.abs(_z_real))
        if _z_imag is not None:
            _z_imag = np.log10(np.abs(_z_imag))

    # if zscale == 'log':
    #     _z_real = np.log(np.abs(_z_real))
    #     if _z_imag is not None:
    #         _z_imag = np.log(np.abs(_z_imag))

    if mode == "sig":
        figure_real = get_heatmap(
            _x, _y, _z_real, zmin=min_scale, zmax=max_scale)
        figure_imag = get_heatmap(
            _x, _y, _z_imag, zmin=min_scale, zmax=max_scale)
    else:
        figure_real = get_heatmap(_x, _y, _z_real)
        figure_imag = get_heatmap(_x, _y, _z_imag)

    colorscale = dict(colorscale=color)
    if mode == "sig":
        colorscale['cmin'] = min_scale
        colorscale['cmax'] = max_scale

    figure_real.update_layout(coloraxis=colorscale)
    figure_imag.update_layout(coloraxis=colorscale)

    figure_real.update_xaxes(side='top')
    figure_real.update_yaxes(autorange='reversed')

    figure_imag.update_xaxes(side='top')
    figure_imag.update_yaxes(autorange='reversed')

    return (figure_real, figure_imag)


def handle_color_heatmap_trigger(figure, color):
    (figure_real, figure_imag) = figure
    colorscale = dict(colorscale=color)
    figure_real = go.Figure(figure_real)
    figure_imag = go.Figure(figure_imag)
    figure_real.update_layout(coloraxis=colorscale)
    figure_imag.update_layout(coloraxis=colorscale)
    return (figure_real, figure_imag)


def handle_scale_heatmap_trigger(figure, color, scale):
    figure_real, figure_imag = figure
    min_scale, max_scale = scale
    colorscale = dict(colorscale=color)
    colorscale['cmin'] = min_scale
    colorscale['cmax'] = max_scale
    figure_real = go.Figure(figure_real)
    figure_imag = go.Figure(figure_imag)
    figure_real.update_layout(coloraxis=colorscale)
    figure_imag.update_layout(coloraxis=colorscale)
    return (figure_real, figure_imag)


@app.callback(
    [dash.dependencies.Output("info-data-timeline-heatmap-real-part", "figure"),
     dash.dependencies.Output(
         "info-data-timeline-heatmap-imag-part", "figure"),
     dash.dependencies.Output("info-timeline", "style")],
    [dash.dependencies.Input("timeline", "hoverData"),
     dash.dependencies.Input("timeline-mode", "value"),
     dash.dependencies.Input('color-heatmap', 'value'),
     dash.dependencies.Input('z-scale', 'value'),
     dash.dependencies.Input('heatmap-formats', 'value'),
     dash.dependencies.Input('minmax-heatmap-button', 'n_clicks'),
     dash.dependencies.State('min-heatmap-input', 'value'),
     dash.dependencies.State('max-heatmap-input', 'value'),
     dash.dependencies.State('info-data-timeline-heatmap-real-part', 'figure'),
     dash.dependencies.State('info-data-timeline-heatmap-imag-part', 'figure'),
     ],
    prevent_initial_call=True)
def print_heatmap(hover_data, mode, color, zscale, heatmap_format, scale_button, min_scale=0, max_scale=53, fig_real={}, fig_imag={}):
    figure_real = go.Figure()
    figure_imag = go.Figure()

    # print('print heatmap')

    display = {"display": "flex", "display-direction": "row"}

    ctx = dash.callback_context

    if ctx.triggered:
        # print(f'ctx triggered {ctx.triggered[0]["prop_id"]}')

        figure = (fig_real, fig_imag)
        scale = (min_scale, max_scale)

        if ctx.triggered[0]['prop_id'] == 'color-heatmap.value':
            return handle_color_heatmap_trigger(figure, color) + (display,)

        if ctx.triggered[0]['prop_id'] == 'minmax-heatmap-button.n_clicks':
            return handle_scale_heatmap_trigger(figure, color, scale) + (display,)

    extra_value = None
    if hover_data:
        x = hover_data['points'][0]['x']
        info = hover_data['points'][0]['customdata']
        extra_value = read_extra_value(x, info, mode)

    if extra_value:

        if heatmap_format == 'heatmap':
            (figure_real, figure_imag) = get_heatmap_figure(figure_real,
                                                            figure_imag,
                                                            extra_value,
                                                            zscale, mode,
                                                            min_scale,
                                                            max_scale, color)

        elif heatmap_format == "graph":
            figure_real = get_graph_figure(figure_real, extra_value)
        elif heatmap_format == "scatter":
            figure_real = get_scatter_figure(figure_real, extra_value)
        else:
            raise ValueError(f'Unkwown format {heatmap_format}')

    # print(figure_real)
    return (figure_real, figure_imag, display)


path_cache = {}


def find_file_in_path(path, filename):
    if path is None:
        return []

    if (key := (path, filename)) in path_cache:
        return path_cache[key]

    subpath = filename.rpartition('site-packages')[-1]
    prefix, name = os.path.split(subpath)

    file_found = None
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for file in files:
                if prefix in root and name == file:
                    file_found = f"{root}{os.sep}{file}"
    if file_found:
        path_cache[(path, filename)] = file_found
    return file_found


__source_line_cache = {}


def get_full_source_line(path, line):
    if (key := (path, line)) in __source_line_cache:
        return __source_line_cache[key]

    fi = open(path)
    source = fi.read()
    m = astroid.parse(source)
    for call in m.nodes_of_class(astroid.Call):
        if call.lineno == int(line):
            source = call.statement()
            key = (path, line)
            __source_line_cache[key] = source
            return source
    return None


@ app.callback(
    dash.dependencies.Output("source", "children"),
    dash.dependencies.Output("source-link", "href"),
    dash.dependencies.Output("source-link", "children"),
    [dash.dependencies.Input("timeline", "hoverData")],
    prevent_initial_call=True)
# @cache.memoize(timeout=TIMEOUT)
def print_source(hover_data):

    line = ""
    source = ""
    description = ""

    if hover_data:
        customdata = hover_data["points"][0]["customdata"]
        source = customdata["filename"]
        _lineno = customdata['lineno']
        path = f"{pgc.data.source_path}{os.sep}{source}"
        if os.path.isfile(path):
            line = get_full_source_line(path, _lineno)
            line = f'```py{os.linesep} {line.as_string()}{os.linesep}```'
        else:
            raise FileNotFoundError
        description = f"{source}:{_lineno}"

    return line, source, description


@ app.callback(
    # dash.dependencies.Output("source-modal-body-md", "children"),
    dash.dependencies.Output("source-file", "children"),
    [dash.dependencies.Input("source-button", "on"),
     dash.dependencies.Input("source-link", "href")],
    dash.dependencies.State('source-link', "children"),
    prevent_initial_call=True)
# @cache.memoize(timeout=TIMEOUT)
def print_modal_source(on, href, href_description):
    source_code = "No source code found..."
    md = None
    if on:
        if href:
            path = f"{pgc.data.source_path}{os.sep}{href}"
            lineno = href_description.split(':')[-1]
            line = get_full_source_line(path, lineno)
            line_start = line.fromlineno
            line_end = line.tolineno
            if os.path.isfile(path):
                fi = open(path)
                source_code = fi.read()
            md = dash_ace.DashAceEditor(id="source-modal-body-md",
                                        value=source_code,
                                        theme='github',
                                        mode='python',
                                        tabSize=2,
                                        focus=True,
                                        enableSnippets=True,
                                        style={"marginBottom": 10,
                                               "width": "100%",
                                               "height": "100%",
                                               "overflowY": "scroll"},
                                        markers=[{'startRow': line_start,
                                                  'startCol': 0,
                                                  'endRow': line_end,
                                                  'endCol': 20,
                                                  'className': 'error-marker',
                                                  'type': 'background'}],
                                        annotations=[{'row': line_start-1,
                                                      'type': 'error', 'text': 'Current call'}])

    return md


@ app.callback(
    dash.dependencies.Output("info-data-timeline-summary", "children"),
    [dash.dependencies.Input("timeline", "hoverData"),
     dash.dependencies.Input("tabs-heatmap", 'value'),
     dash.dependencies.Input("info-data-timeline-heatmap-real-part", "figure"),
     dash.dependencies.Input("info-data-timeline-heatmap-imag-part", "figure"),
     dash.dependencies.Input("heatmap-formats", "value")
     ],
    dash.dependencies.State('timeline-mode', 'value'),
    prevent_initial_call=True)
def print_datahover_summary(hover_data, tab, fig_real, fig_imag, heatmap_format, mode):
    text = ""

    if tab == 'tab-real-part':
        fig = fig_real
    elif tab == 'tab-imag-part':
        fig = fig_imag
    else:
        fig = None

    # print(f'hover_data {hover_data}')
    # print(f'figure {fig}')

    if not fig or not hover_data or fig['data'] == []:
        return text

    if hover_data:
        info = hover_data['points'][0]['customdata']

        if heatmap_format == 'heatmap':
            _ndarray = np.array(fig['data'][0]['z'])
        elif heatmap_format == 'graph':
            text = (f"Function={info['function'].strip()}",
                    f"Arg     ={info['arg'].strip()}")
            return os.linesep.join(map(lambda x: f"- {x.replace(' ', ' &nbsp;')}", text))
    else:
        return text

    try:
        _min = np.min(_ndarray)
        _max = np.max(_ndarray)
        _is_nan = False
    except Exception:
        _is_nan = True
        _min = np.nan
        _max = np.nan
        _size = _ndarray.shape
        norm_fro = np.nan
        norm_inf = np.nan
        cond = np.nan
        text = (f"Function={info['function'].strip()}",
                f"Arg     ={info['arg'].strip()}",
                f"Shape   ={_size}",
                f"Fro norm={norm_fro:.2}",
                f"Inf norm={norm_inf:.2}",
                f"Cond    ={cond:.2e}",
                f"Min     ={_min:.2e}",
                f"Max     ={_max:.2e}"
                )
    # _min = np.min(_ndarray)
    # _max = np.max(_ndarray)

    ndim = _ndarray.ndim

    if _is_nan:
        pass
    elif ndim == 1:
        # if ndim == 1:
        (_size,) = _ndarray.shape
        norm_fro = np.linalg.norm(_ndarray)
        norm_inf = np.linalg.norm(_ndarray, ord=np.inf)
        cond = 1/norm_fro
        text = (f"Function={info['function'].strip()}",
                f"Arg     ={info['arg'].strip()}",
                f"Shape   ={_size}",
                f"Fro norm={norm_fro:.2}",
                f"Inf norm={norm_inf:.2}",
                f"Cond    ={cond:.2e}",
                f"Min     ={_min:.2e}",
                f"Max     ={_max:.2e}"
                )

    elif ndim == 2:
        _row, _col = _ndarray.shape
        norm_fro = np.linalg.norm(_ndarray)
        norm_inf = np.linalg.norm(_ndarray, ord=np.inf)
        norm_2 = np.linalg.norm(_ndarray, ord=2)
        cond = np.linalg.cond(_ndarray)
        text = (f"Function={info['function'].strip()}",
                f"Arg     ={info['arg'].strip()}",
                f"Shape   ={_row}x{_col}",
                f"Fro norm={norm_fro:.2}",
                f"Inf norm={norm_inf:.2}",
                f"2-norm  ={norm_2:.2}",
                f"Cond    ={cond:.2e}",
                f"Min     ={_min:.2e}",
                f"Max     ={_max:.2e}"
                )

    elif ndim > 2:
        shape = "x".join(map(str, _ndarray.shape))
        norm_fro = np.linalg.norm(_ndarray)
        text = (f"Function={info['function'].strip()}",
                f"Arg     ={info['arg'].strip()}",
                f"Shape   ={shape}",
                f"Fro norm={norm_fro:.2}",
                f"Min     ={_min:.2e}",
                f"Max     ={_max:.2e}"
                )
    return os.linesep.join(map(lambda x: f"- {x.replace(' ', ' &nbsp;')}", text))


@ app.callback(
    dash.dependencies.Output("source-file", "style"),
    dash.dependencies.Input("source-button", "on"))
def open_modal_source(on):
    style_off = {"display": "none"}
    style_on = {"display": "block", "width": "100%", "height": 300}
    return style_on if on else style_off


def is_object(y):
    try:
        if y == []:
            return True
        if not np.can_cast(y[0], np.number):
            return True
        if np.isnan(y[0]):
            return True
        if 'nan' in y or b'nan' in y:
            return True
        if 'None' in y or b'None' in y:
            return True
    except Exception as e:
        return True
    return False

# @cache.memoize(timeout=TIMEOUT)


def get_scatter_timeline(module, function, label, backtrace, arg, mode, marker_symbol,
                         marker_color, customdata=None):

    def get_x(values, col, *argv):
        arg = argv[0]
        label = argv[1]
        b_label = bytes(label, "utf-8")
        with lock:
            return [x[col] for x in values.where(
                '((name == arg) & (label == b_label))')
                if x["BacktraceDescription"] == backtrace
            ]

    x = pgc.data.filter(module, function, get_x, "time", arg, label)
    y = pgc.data.filter(module, function, get_x, mode, arg, label)
    dtype = pgc.data.filter(module, function, get_x, 'dtype', arg, label)
    dtype = dtype[0].decode('utf-8') if dtype != [] else ''
    (filename, line, lineno, name) = backtrace

    decoded_arg = arg.decode('utf-8')

    info = {'module': module,
            'function': function,
            'label': label,
            'arg': decoded_arg,
            'filename': filename.decode('utf-8'),
            'lineno': lineno,
            'name': name.decode('utf-8'),
            'dtype': dtype
            }

    _is_object = is_object(y)
    y = [1] * len(y) if _is_object else y
    _str = pgc.data.filter(module, function, get_x, 'info',
                           arg, label) if _is_object else None
    marker_symbol = 'star' if _is_object else marker_symbol
    # y = [1] * len(y) if _is_object else None

    customdata = [{**info, 'time': i} for i in x]
    _hovertext = '<br>'.join([function, decoded_arg, dtype]) + os.linesep
    hovertext = [_hovertext] * len(x)

    hovertemplate = ('<b>X</b>: %{x}',
                     '<b>Y</b>: %{y:7e}',
                     '<b>%{text}</b>')

    if _is_object and _str != []:
        description = f"<b>{_str[0].decode('utf-8')}</b>"
        hovertemplate += (description,)

    hovertemplate = '<br>'.join(hovertemplate)

    name = f"{function} - {decoded_arg} - {lineno}"

    scatter = go.Scattergl(name=name,
                           #    legendgroup=f"group{backtrace}",
                           x=x,
                           y=y,
                           hovertemplate=hovertemplate,
                           #    '<b>X</b>: %{x}' +
                           #    '<br><b>Y</b>: %{y:.7e}<br>' +
                           #    '<b>%{text}</b>',
                           text=hovertext,
                           customdata=customdata,
                           mode="markers",
                           marker_symbol=marker_symbol,
                           marker_color=marker_color,
                           marker_size=10,
                           marker_opacity=0.5,
                           meta={'module': module, 'function': function})
    return scatter

# @cache.memoize(timeout=TIMEOUT)


def add_scatter(fig, module, function,
                label, backtraces_set,
                argsname, colors, marker, mode):

    for backtrace in backtraces_set:
        for arg in argsname:
            # ori_arg = find_calling_name(backtrace, arg)
            scatter = get_scatter_timeline(module,
                                           function,
                                           label,
                                           backtrace,
                                           arg,
                                           mode,
                                           marker,
                                           colors[backtrace])

            fig.add_trace(scatter)

# @cache.memoize(timeout=TIMEOUT)


def get_name(astname):
    if isinstance(astname, astroid.Attribute):
        name = get_name(astname.expr)
        attr = astname.attr
        return f"{name}.{attr}"
    elif isinstance(astname, astroid.Name):
        name = astname.Name
        return f"{name}"
    elif isinstance(astname, astroid.Const):
        name = astname.value
        return f"{name}"
    else:
        raise TypeError

# @cache.memoize(timeout=TIMEOUT)


def get_first_call_from_line(lfile, lstart):
    src = None
    with open(lfile) as fi:
        src = "\n".join([_ for _ in fi])
    m = astroid.parse(src)
    calls = m.nodes_of_class(astroid.Call)
    calls_list = []
    for call in calls:
        if call.lineno == lstart:
            calls_list.append(get_name(call.func))
    return calls_list


_colors_map = dict()


def get_colors(module, function):
    if (key := (module, function)) in _colors_map:
        return _colors_map[key]

    def get_x_in(values, col):
        b_inputs = b"inputs"
        with lock:
            return [x[col] for x in values.where('((label == b_inputs))')]

    def get_x_out(values, col):
        b_outputs = b"outputs"
        with lock:
            return [x[col] for x in values.where('((label == b_outputs))')]

    backtraces_in = pgc.data.filter(
        module, function, get_x_in, "BacktraceDescription")

    backtraces_out = pgc.data.filter(
        module, function, get_x_out, "BacktraceDescription")

    backtraces_set = set.union(set(backtraces_in), set(backtraces_out))

    _colors = pcolors.qualitative.Dark24 * 10
    random.shuffle(_colors)
    colors = {bt: _colors[i]
              for i, bt in enumerate(backtraces_set)}

    key = (module, function)
    value = (colors, backtraces_set)
    _colors_map[key] = value
    return value


def remove_scatter(figure, module, function):
    meta_to_remove = {'module': module, "function": function}
    for data in figure['data']:
        if data['meta'] == meta_to_remove:
            data['visible'] = False


@ app.callback(
    dash.dependencies.Output("download-timeline", "data"),
    dash.dependencies.Input("dump-timeline", "n_clicks"),
    dash.dependencies.State("timeline", "figure"),
    prevent_initial_call=True
)
def dump_timeline(n_clicks, figure):
    data = json.dumps(figure, ensure_ascii=False, indent=2)
    return dict(content=data, filename='timeline.json')


@ app.callback(
    dash.dependencies.Output("download-heatmap", "data"),
    dash.dependencies.Input("dump-heatmap-button", "n_clicks"),
    dash.dependencies.State('tabs-heatmap', 'value'),
    dash.dependencies.State("info-data-timeline-heatmap-real-part", "figure"),
    dash.dependencies.State("info-data-timeline-heatmap-real-part", "figure"),
    prevent_initial_call=True
)
def dump_heatmap_real(n_clicks, tab, figure_real, figure_imag):
    if tab == "tab-real-part":
        data = json.dumps(figure_real, ensure_ascii=False, indent=2)
        name = 'heatmap-real.json'
    elif tab == 'tab-imag-part':
        data = json.dumps(figure_imag, ensure_ascii=False, indent=2)
        name = 'heatmap-imag.json'
    else:
        raise Exception(f'Unknown tab {tab}')

    return dict(content=data, filename=name)


@ app.callback(
    dash.dependencies.Output("current-selected-rows", "data"),
    dash.dependencies.Output("previous-selected-rows", "data"),
    dash.dependencies.Input("info-table", "selected_rows"),
    dash.dependencies.State("current-selected-rows", "data")
)
def update_selected_rows(selected_rows, current_selection):
    return (selected_rows, current_selection)


@ app.callback(
    dash.dependencies.Output("timeline", "figure"),
    [dash.dependencies.Input("current-selected-rows", "data"),
     dash.dependencies.Input("info-table", "data"),
     dash.dependencies.Input("timeline-mode", "value"),
     dash.dependencies.Input("x-scale", "value"),
     dash.dependencies.Input("y-scale", "value"),
     dash.dependencies.Input("x-format", "value"),
     dash.dependencies.Input("y-format", "value"),
     dash.dependencies.State("timeline", "figure"),
     dash.dependencies.State("previous-selected-rows", "data"),
     ])
def update_timeline(selected_rows, data, mode, xscale, yscale,
                    xfmt, yfmt, curr_fig, prev_selected_rows):
    ctx = dash.callback_context

    b = time.perf_counter()
    if ctx.triggered:
        trigger = ctx.triggered[0]['prop_id']
        if trigger in ("x-scale.value", 'y-scale.value', 'x-format.value', 'y-format.value'):
            value = ctx.triggered[0]['value']
            fig = go.Figure(curr_fig)
            if trigger == 'x-scale.value':
                fig.update_xaxes(type=value)
            elif trigger == 'x-format.value':
                fig.update_xaxes(tickformat=value)
            elif trigger == 'y-scale.value':
                fig.update_yaxes(type=value)
            elif trigger == 'y-format.value':
                fig.update_yaxes(tickformat=value)
            return fig

    new_fig = go.Figure(
        layout={'height': 800,
                'modebar': {'orientation': 'v'}
                # 'paper_bgcolor': 'hsla(0,0%,0%,0%)',
                # 'plot_bgcolor': 'hsla(0,0%,0%,0%)',
                # 'xaxis': {'gridcolor': 'grey'},
                # 'axis': {'gridcolor': 'grey'}
                }
    )

    if curr_fig is None:
        fig = new_fig
    else:
        fig = go.Figure(curr_fig)

    if selected_rows == []:
        return new_fig
    else:
        rows_to_add = set.difference(
            set(selected_rows), set(prev_selected_rows))
        rows_to_remove = set.difference(
            set(prev_selected_rows), set(selected_rows))

    ylabel = pgc.get_ylabel(mode)
    fig.update_xaxes(title_text="Invocation", type=xscale)
    fig.update_yaxes(title_text=ylabel,
                     rangemode="tozero", type=yscale)

    module_and_function_to_add = [data[x] for x in rows_to_add]
    module_and_function_to_remove = [data[x] for x in rows_to_remove]

    # @cache.memoize(timeout=TIMEOUT)

    def get_x_in(values, col):
        b_inputs = b"inputs"
        with lock:
            return [x[col] for x in values.where('((label == b_inputs))')]

    # @cache.memoize(timeout=TIMEOUT)
    def get_x_out(values, col, *argv):
        b_outputs = b"outputs"
        with lock:
            return [x[col] for x in values.where('((label == b_outputs))')]

    for mf in module_and_function_to_add:
        module = mf["module"]
        function = mf["function"]

        colors, backtraces_set = get_colors(module, function)

        names = pgc.data.filter(
            module, function, get_x_in, "name")
        argsname = set(names)

        add_scatter(fig=fig,
                    module=module, function=function,
                    label="inputs", backtraces_set=backtraces_set,
                    argsname=argsname, colors=colors, marker="triangle-up", mode=mode)

        names = pgc.data.filter(
            module, function, get_x_out, "name")
        argsname = set(names)

        add_scatter(fig=fig,
                    module=module, function=function,
                    label="outputs", backtraces_set=backtraces_set,
                    argsname=argsname, colors=colors, marker="triangle-down", mode=mode)

    for mf in module_and_function_to_remove:
        module = mf["module"]
        function = mf["function"]
        remove_scatter(figure=fig, module=module, function=function)

    e = time.perf_counter()
    print("update_timeline", e-b)
    # print(fig.data)
    return fig


@app.callback(
    dash.dependencies.Output("histo_bin_selected", "children"),
    [dash.dependencies.Input("histo_bin_selector", "value")]
)
def update_histo_bin_selected(nb_bins):
    return f"Nb bins: {nb_bins}"


@app.callback(
    dash.dependencies.Output("histo_heatmap", "figure"),
    [dash.dependencies.Input('tabs-heatmap', 'value'),
     dash.dependencies.Input("info-data-timeline-heatmap-real-part", "figure"),
     dash.dependencies.Input("info-data-timeline-heatmap-imag-part", "figure"),
     dash.dependencies.Input("histo_bin_selector", "value"),
     dash.dependencies.Input("histo_normalization", "value")],
    dash.dependencies.State("timeline-mode", "value"))
def update_histo(tabs, heatmap_real, heatmap_imag, nbins, normalization, mode):
    if tabs == 'tab-real-part':
        heatmap = heatmap_real
    elif tabs == 'tab-imag-part':
        heatmap = heatmap_imag
    else:
        heatmap = None

    if heatmap == {} or heatmap is None:
        return {}

    if 'data' in heatmap and len(heatmap['data']) > 0 and 'z' in heatmap['data'][0]:
        x = np.ravel(heatmap['data'][0]['z'])
    else:
        return go.Figure()

    fig = get_histo(x, nbins, normalization)

    mode_str = {"sig": "Significant digits",
                "mean": "Mean", "std": "Standard deviation"}
    fig.update_xaxes({"title": mode_str[mode]})
    fig.update_yaxes({"title": normalization if normalization else "count"})
    return fig


def get_histo(x, nbins, normalization):
    return go.Figure(data=go.Histogram(x=x, nbinsx=nbins, histnorm=normalization))
