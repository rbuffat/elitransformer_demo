import glob
import io
import json
import os
from datetime import date

from fiona.crs import from_epsg
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, GeometryCollection
from shapely.ops import cascaded_union
from shapely.validation import make_valid
import fiona

eli_path = r"editor-layer-index/sources"
out_file = r"imagery.geojson"

ignore_list = {'osmbe',  # 'OpenStreetMap (Belgian Style)'
               'osmfr',  # 'OpenStreetMap (French Style)'
               'osm-mapnik-german_style',  # 'OpenStreetMap (German Style)'
               'HDM_HOT',  # 'OpenStreetMap (HOT Style)'
               'osm-mapnik-black_and_white',  # 'OpenStreetMap (Standard Black & White)'
               'osm-mapnik-no_labels',  # 'OpenStreetMap (Mapnik, no labels)'
               'OpenStreetMap-turistautak',  # 'OpenStreetMap (turistautak)'

               'hike_n_bike',  # 'Hike & Bike'
               'landsat',  # 'Landsat'
               'skobbler',  # 'Skobbler'
               'public_transport_oepnv',  # 'Public Transport (ÖPNV)'
               'tf-cycle',  # 'Thunderforest OpenCycleMap'
               'tf-landscape',  # 'Thunderforest Landscape'
               'tf-outdoors',  # 'Thunderforest Outdoors'
               'qa_no_address',  # 'QA No Address'
               'wikimedia-map',  # 'Wikimedia Map'

               'openinframap-petroleum',
               'openinframap-power',
               'openinframap-telecoms',
               'openpt_map',
               'openrailwaymap',
               'openseamap',
               'opensnowmap-overlay',

               'US-TIGER-Roads-2012',
               'US-TIGER-Roads-2014',

               'Waymarked_Trails-Cycling',
               'Waymarked_Trails-Hiking',
               'Waymarked_Trails-Horse_Riding',
               'Waymarked_Trails-MTB',
               'Waymarked_Trails-Skating',
               'Waymarked_Trails-Winter_Sports',

               'OSM_Inspector-Addresses',
               'OSM_Inspector-Geometry',
               'OSM_Inspector-Highways',
               'OSM_Inspector-Multipolygon',
               'OSM_Inspector-Places',
               'OSM_Inspector-Routing',
               'OSM_Inspector-Tagging',

               'EOXAT2018CLOUDLESS'}

# TODO what about CRS:84?
supported_projections = {
    # Web Mercator
    'EPSG:3857',
    # alternate codes used for Web Mercator
    'EPSG:900913',
    'EPSG:3587',
    'EPSG:54004',
    'EPSG:41001',
    'EPSG:102113',
    'EPSG:102100',
    'EPSG:3785',
    # WGS 84 (Equirectangular)
    'EPSG:4326'}


def make_geom_valid(geometry):
    """ Transform invalid geometries to valid geometries

    Parameters
    ----------
    geometry: the geometry

    Returns
    -------

    """
    if geometry is None:
        return geometry

    geom = shape(geometry)
    if not geom.is_valid:
        geom = make_valid(geom)
        # Keep only polygons and multipolygons
        if isinstance(geom, GeometryCollection):
            keep = []
            for g in geom.geoms:
                if isinstance(g, Polygon) or isinstance(g, MultiPolygon):
                    keep.append(g)
            geom = cascaded_union(keep)

        if not (isinstance(geom, Polygon) or isinstance(geom, MultiPolygon)):
            raise ValueError("Geometry not Polygon: {}".format(type(geom)))
    geometry = mapping(geom)
    return geometry


def simplify_geometry(geometry):
    """ Simplify geometry to reduce size"""
    if geometry is None:
        return geometry

    # TODO: This needs more investigation. It might be better to transform the geometry first to EPSG:3587
    geom = shape(geometry).simplify(0.01)
    geometry = make_geom_valid(mapping(geom))
    return geometry


def process_sources():
    # Schema of output file
    schema = {'properties': {
                             'best': 'int:1',
                             'country_code': 'str',
                             'end_date': 'str',
                             'id': 'str',
                             'license_url': 'str',
                             'max_zoom': 'int',
                             'name': 'str',
                             'start_date': 'str',
                             'type': 'str',
                             'url': 'str',
                             'attribution': 'str',
                             # 'description': 'str',
                             'icon': 'str',
                             'min_zoom': 'int',
                             # 'permission_osm': 'str',
                             'privacy_policy_url': 'str',
                             'available_projections': 'str',
                             'i18n': 'int:1',
                             'overlay': 'int:1',
                             # 'category': 'str',
                             # 'default': 'int:1',
                             # 'valid-georeference': 'int:1',
                             # 'no_tile_header': 'str'
                             },
              'geometry': 'Unknown'}

    with fiona.open(out_file,
                    mode='w',
                    driver='GeoJSON',
                    crs=from_epsg(4326),
                    schema=schema,
                    COORDINATE_PRECISION=4) as out:

        for filename in glob.glob(os.path.join(eli_path, '**', '*.geojson'), recursive=True):
            source = json.load(io.open(filename, encoding='utf-8'))

            if source['properties']['id'] in ignore_list:
                continue

            # Filter not supported imagery types
            if source['properties']['type'] not in {'tms', 'wms', 'bing'}:
                continue

            # Ensure that geometries are valid
            source['geometry'] = make_geom_valid(source['geometry'])

            # Simplify geoemtry
            source['geometry'] = simplify_geometry(source['geometry'])

            # Filter WMS imagery without compatible projections
            if source['properties']['type'] == 'wms':

                # WMS sources require available_projections
                if 'available_projections' not in source['properties']:
                    continue

                if not any([proj in supported_projections for proj in source['properties']['available_projections']]):
                    continue

            # Filter old imagery
            if 'end_date' in source['properties']:
                end_date = int(source['properties']['end_date'].split("-")[0])
                if end_date < date.today().year - 20:
                    continue

            # Min / max zooms
            # TODO calculate based on size of geometry?
            if 'min_zoom' not in source:
                source['properties']['min_zoom'] = 0
            if 'max_zoom' not in source:
                source['properties']['max_zoom'] = 22

            # Fill missing elements with default values
            # TODO find better solution
            for key, val in schema['properties'].items():
                if key not in source:
                    _val = val.split(":")[0]
                    if _val == 'str':
                        source['properties'][key] = ''
                    else:
                        source['properties'][key] = 0
            for key in list(source['properties'].keys()):
                if key not in schema['properties']:
                    source['properties'].pop(key)

            out.write(source)


process_sources()
