"""Localidades argentinas con su código postal de referencia (CU09).

Muchos compradores escriben la ciudad en lugar del código postal («¿llegan a Río
Cuarto?»). Con esta tabla el bot resuelve el plazo sin volver a preguntar. Se usa el
código postal clásico de 4 dígitos del centro de cada localidad, que es el que define la
zona de envío del comercio (las zonas son rangos de códigos postales).

Reglas:
- Solo se buscan localidades cuando el mensaje habla de envíos o cuando el bot está
  esperando el código postal, para no confundir «azul» (color) con Azul (Buenos Aires).
- Las localidades con nombres repetidos en varias provincias («San Martín», «Mercedes»)
  se marcan como ambiguas: el bot pide el código postal.
- Para una provincia se toma como referencia su capital y el bot lo aclara.
- «Buenos Aires» sin más datos es ambigua (Ciudad o provincia, con plazos distintos).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Localidad:
    nombre: str
    provincia: str
    cp: int
    # La localidad se nombró por su provincia («Chubut»): el código es el de la capital.
    es_provincia: bool = False
    # El nombre también es una palabra común o un nombre de persona («Azul», «Pilar»):
    # solo se reconoce cuando el mensaje habla de envíos.
    nombre_comun: bool = False


@dataclass(frozen=True)
class LocalidadAmbigua:
    nombre: str
    opciones: tuple[str, ...]


def _l(nombre, provincia, cp, **kw) -> Localidad:
    return Localidad(nombre, provincia, cp, **kw)


# Capitales y provincias -----------------------------------------------------------------

_CABA = _l("Ciudad de Buenos Aires", "CABA", 1000)

LOCALIDADES: dict[str, Localidad | LocalidadAmbigua] = {
    # Ciudad de Buenos Aires
    "caba": _CABA,
    "capital federal": _CABA,
    "ciudad de buenos aires": _CABA,
    "ciudad autonoma de buenos aires": _CABA,
    "ciudad autonoma": _CABA,
    "buenos aires capital": _CABA,
    "capital": LocalidadAmbigua("Capital", ("Ciudad de Buenos Aires", "la capital de tu provincia")),
    "buenos aires": LocalidadAmbigua("Buenos Aires", ("Ciudad de Buenos Aires", "provincia de Buenos Aires")),
    "provincia de buenos aires": LocalidadAmbigua("provincia de Buenos Aires", ()),
    "gran buenos aires": LocalidadAmbigua("Gran Buenos Aires", ()),
    "gba": LocalidadAmbigua("Gran Buenos Aires", ()),
    "conurbano": LocalidadAmbigua("Conurbano bonaerense", ()),
    "zona sur": LocalidadAmbigua("zona sur", ()),
    "zona norte": LocalidadAmbigua("zona norte", ()),
    "zona oeste": LocalidadAmbigua("zona oeste", ()),
    # Capitales de provincia (y el nombre de la provincia cuando coincide)
    "la plata": _l("La Plata", "Buenos Aires", 1900, nombre_comun=True),
    "cordoba": _l("Córdoba", "Córdoba", 5000),
    "cordoba capital": _l("Córdoba", "Córdoba", 5000),
    "ciudad de cordoba": _l("Córdoba", "Córdoba", 5000),
    "provincia de cordoba": LocalidadAmbigua("provincia de Córdoba", ()),
    "santa fe": _l("Santa Fe", "Santa Fe", 3000),
    "santa fe capital": _l("Santa Fe", "Santa Fe", 3000),
    "ciudad de santa fe": _l("Santa Fe", "Santa Fe", 3000),
    "provincia de santa fe": LocalidadAmbigua("provincia de Santa Fe", ()),
    "mendoza": _l("Mendoza", "Mendoza", 5500),
    "san juan": _l("San Juan", "San Juan", 5400),
    "san luis": _l("San Luis", "San Luis", 5700),
    "la rioja": _l("La Rioja", "La Rioja", 5300),
    "catamarca": _l("San Fernando del Valle de Catamarca", "Catamarca", 4700),
    "san fernando del valle de catamarca": _l("San Fernando del Valle de Catamarca", "Catamarca", 4700),
    "tucuman": _l("San Miguel de Tucumán", "Tucumán", 4000),
    "san miguel de tucuman": _l("San Miguel de Tucumán", "Tucumán", 4000),
    "santiago del estero": _l("Santiago del Estero", "Santiago del Estero", 4200),
    "salta": _l("Salta", "Salta", 4400),
    "jujuy": _l("San Salvador de Jujuy", "Jujuy", 4600),
    "san salvador de jujuy": _l("San Salvador de Jujuy", "Jujuy", 4600),
    "formosa": _l("Formosa", "Formosa", 3600),
    "corrientes": _l("Corrientes", "Corrientes", 3400),
    "neuquen": _l("Neuquén", "Neuquén", 8300),
    "resistencia": _l("Resistencia", "Chaco", 3500, nombre_comun=True),
    "chaco": _l("Resistencia", "Chaco", 3500, es_provincia=True),
    "posadas": _l("Posadas", "Misiones", 3300),
    "misiones": _l("Posadas", "Misiones", 3300, es_provincia=True),
    "parana": _l("Paraná", "Entre Ríos", 3100),
    "entre rios": _l("Paraná", "Entre Ríos", 3100, es_provincia=True),
    "santa rosa": _l("Santa Rosa", "La Pampa", 6300),
    "la pampa": _l("Santa Rosa", "La Pampa", 6300, es_provincia=True),
    "viedma": _l("Viedma", "Río Negro", 8500),
    "rio negro": _l("Viedma", "Río Negro", 8500, es_provincia=True),
    "rawson": _l("Rawson", "Chubut", 9103),
    "chubut": _l("Rawson", "Chubut", 9103, es_provincia=True),
    "rio gallegos": _l("Río Gallegos", "Santa Cruz", 9400),
    "santa cruz": _l("Río Gallegos", "Santa Cruz", 9400, es_provincia=True),
    "ushuaia": _l("Ushuaia", "Tierra del Fuego", 9410),
    "tierra del fuego": _l("Ushuaia", "Tierra del Fuego", 9410, es_provincia=True),
    # Córdoba
    "rio cuarto": _l("Río Cuarto", "Córdoba", 5800),
    "rio 4": _l("Río Cuarto", "Córdoba", 5800),
    "villa maria": _l("Villa María", "Córdoba", 5900),
    "carlos paz": _l("Villa Carlos Paz", "Córdoba", 5152),
    "villa carlos paz": _l("Villa Carlos Paz", "Córdoba", 5152),
    "san francisco": _l("San Francisco", "Córdoba", 2400),
    "alta gracia": _l("Alta Gracia", "Córdoba", 5186),
    "jesus maria": _l("Jesús María", "Córdoba", 5220),
    "bell ville": _l("Bell Ville", "Córdoba", 2550),
    "villa dolores": _l("Villa Dolores", "Córdoba", 5870),
    "rio tercero": _l("Río Tercero", "Córdoba", 5850),
    "rio segundo": _l("Río Segundo", "Córdoba", 5960),
    "cosquin": _l("Cosquín", "Córdoba", 5166),
    "la falda": _l("La Falda", "Córdoba", 5172),
    "villa general belgrano": _l("Villa General Belgrano", "Córdoba", 5194),
    "marcos juarez": _l("Marcos Juárez", "Córdoba", 2580),
    "laboulaye": _l("Laboulaye", "Córdoba", 6120),
    "cruz del eje": _l("Cruz del Eje", "Córdoba", 5280),
    "dean funes": _l("Deán Funes", "Córdoba", 5200),
    "arroyito": _l("Arroyito", "Córdoba", 2434),
    "oncativo": _l("Oncativo", "Córdoba", 5986),
    "villa allende": _l("Villa Allende", "Córdoba", 5105),
    "rio ceballos": _l("Río Ceballos", "Córdoba", 5111),
    "unquillo": _l("Unquillo", "Córdoba", 5109),
    "la calera": _l("La Calera", "Córdoba", 5151),
    "mina clavero": _l("Mina Clavero", "Córdoba", 5889),
    "capilla del monte": _l("Capilla del Monte", "Córdoba", 5184),
    "santa rosa de calamuchita": _l("Santa Rosa de Calamuchita", "Córdoba", 5196),
    "embalse": _l("Embalse", "Córdoba", 5856, nombre_comun=True),
    # Santa Fe
    "rosario": _l("Rosario", "Santa Fe", 2000, nombre_comun=True),
    "rafaela": _l("Rafaela", "Santa Fe", 2300, nombre_comun=True),
    "venado tuerto": _l("Venado Tuerto", "Santa Fe", 2600),
    "reconquista": _l("Reconquista", "Santa Fe", 3560, nombre_comun=True),
    "villa gobernador galvez": _l("Villa Gobernador Gálvez", "Santa Fe", 2124),
    "casilda": _l("Casilda", "Santa Fe", 2170, nombre_comun=True),
    "esperanza": _l("Esperanza", "Santa Fe", 3080, nombre_comun=True),
    "cañada de gomez": _l("Cañada de Gómez", "Santa Fe", 2500),
    "funes": _l("Funes", "Santa Fe", 2132, nombre_comun=True),
    "firmat": _l("Firmat", "Santa Fe", 2630),
    "rufino": _l("Rufino", "Santa Fe", 6100, nombre_comun=True),
    "granadero baigorria": _l("Granadero Baigorria", "Santa Fe", 2152),
    "villa constitucion": _l("Villa Constitución", "Santa Fe", 2919),
    "san lorenzo": _l("San Lorenzo", "Santa Fe", 2200, nombre_comun=True),
    # Provincia de Buenos Aires
    "mar del plata": _l("Mar del Plata", "Buenos Aires", 7600),
    "bahia blanca": _l("Bahía Blanca", "Buenos Aires", 8000),
    "tandil": _l("Tandil", "Buenos Aires", 7000),
    "olavarria": _l("Olavarría", "Buenos Aires", 7400),
    "junin": _l("Junín", "Buenos Aires", 6000),
    "pergamino": _l("Pergamino", "Buenos Aires", 2700),
    "azul": _l("Azul", "Buenos Aires", 7300, nombre_comun=True),
    "necochea": _l("Necochea", "Buenos Aires", 7630),
    "tres arroyos": _l("Tres Arroyos", "Buenos Aires", 7500),
    "san nicolas": _l("San Nicolás de los Arroyos", "Buenos Aires", 2900),
    "zarate": _l("Zárate", "Buenos Aires", 2800, nombre_comun=True),
    "campana": _l("Campana", "Buenos Aires", 2804, nombre_comun=True),
    "lujan": _l("Luján", "Buenos Aires", 6700, nombre_comun=True),
    "chivilcoy": _l("Chivilcoy", "Buenos Aires", 6620),
    "bragado": _l("Bragado", "Buenos Aires", 6640),
    "nueve de julio": _l("Nueve de Julio", "Buenos Aires", 6500, nombre_comun=True),
    "trenque lauquen": _l("Trenque Lauquen", "Buenos Aires", 6400),
    "pehuajo": _l("Pehuajó", "Buenos Aires", 6450),
    "chascomus": _l("Chascomús", "Buenos Aires", 7130),
    "dolores": _l("Dolores", "Buenos Aires", 7100, nombre_comun=True),
    "pinamar": _l("Pinamar", "Buenos Aires", 7167),
    "villa gesell": _l("Villa Gesell", "Buenos Aires", 7165),
    "miramar": _l("Miramar", "Buenos Aires", 7607),
    "balcarce": _l("Balcarce", "Buenos Aires", 7620),
    "coronel suarez": _l("Coronel Suárez", "Buenos Aires", 7540),
    "punta alta": _l("Punta Alta", "Buenos Aires", 8109),
    "san antonio de areco": _l("San Antonio de Areco", "Buenos Aires", 2760),
    "lobos": _l("Lobos", "Buenos Aires", 7240, nombre_comun=True),
    "cañuelas": _l("Cañuelas", "Buenos Aires", 1814),
    # Gran Buenos Aires
    "quilmes": _l("Quilmes", "Buenos Aires", 1878),
    "avellaneda": _l("Avellaneda", "Buenos Aires", 1870),
    "lanus": _l("Lanús", "Buenos Aires", 1824),
    "lomas de zamora": _l("Lomas de Zamora", "Buenos Aires", 1832),
    "banfield": _l("Banfield", "Buenos Aires", 1828),
    "temperley": _l("Temperley", "Buenos Aires", 1834),
    "adrogue": _l("Adrogué", "Buenos Aires", 1846),
    "berazategui": _l("Berazategui", "Buenos Aires", 1884),
    "florencio varela": _l("Florencio Varela", "Buenos Aires", 1888),
    "moron": _l("Morón", "Buenos Aires", 1708),
    "castelar": _l("Castelar", "Buenos Aires", 1712, nombre_comun=True),
    "ituzaingo": _l("Ituzaingó", "Buenos Aires", 1714),
    "moreno": _l("Moreno", "Buenos Aires", 1744, nombre_comun=True),
    "ramos mejia": _l("Ramos Mejía", "Buenos Aires", 1704),
    "haedo": _l("Haedo", "Buenos Aires", 1706),
    "san isidro": _l("San Isidro", "Buenos Aires", 1642),
    "vicente lopez": _l("Vicente López", "Buenos Aires", 1638),
    "olivos": _l("Olivos", "Buenos Aires", 1636, nombre_comun=True),
    "martinez": _l("Martínez", "Buenos Aires", 1640, nombre_comun=True),
    "tigre": _l("Tigre", "Buenos Aires", 1648, nombre_comun=True),
    "caseros": _l("Caseros", "Buenos Aires", 1678, nombre_comun=True),
    "pilar": _l("Pilar", "Buenos Aires", 1629, nombre_comun=True),
    "escobar": _l("Belén de Escobar", "Buenos Aires", 1625, nombre_comun=True),
    "jose c paz": _l("José C. Paz", "Buenos Aires", 1665),
    "bernal": _l("Bernal", "Buenos Aires", 1876, nombre_comun=True),
    "ezeiza": _l("Ezeiza", "Buenos Aires", 1804),
    "monte grande": _l("Monte Grande", "Buenos Aires", 1842),
    "burzaco": _l("Burzaco", "Buenos Aires", 1852),
    "hurlingham": _l("Hurlingham", "Buenos Aires", 1686),
    "villa ballester": _l("Villa Ballester", "Buenos Aires", 1653),
    "wilde": _l("Wilde", "Buenos Aires", 1875, nombre_comun=True),
    "sarandi": _l("Sarandí", "Buenos Aires", 1872),
    "ensenada": _l("Ensenada", "Buenos Aires", 1925, nombre_comun=True),
    "berisso": _l("Berisso", "Buenos Aires", 1923),
    "city bell": _l("City Bell", "Buenos Aires", 1896),
    "ciudadela": _l("Ciudadela", "Buenos Aires", 1702, nombre_comun=True),
    "laferrere": _l("Gregorio de Laferrere", "Buenos Aires", 1757),
    "gonzalez catan": _l("González Catán", "Buenos Aires", 1759),
    "isidro casanova": _l("Isidro Casanova", "Buenos Aires", 1765),
    "don torcuato": _l("Don Torcuato", "Buenos Aires", 1611),
    "munro": _l("Munro", "Buenos Aires", 1605),
    "boulogne": _l("Boulogne", "Buenos Aires", 1609),
    "general rodriguez": _l("General Rodríguez", "Buenos Aires", 1748),
    "marcos paz": _l("Marcos Paz", "Buenos Aires", 1727),
    # Cuyo
    "san rafael": _l("San Rafael", "Mendoza", 5600),
    "godoy cruz": _l("Godoy Cruz", "Mendoza", 5501),
    "lujan de cuyo": _l("Luján de Cuyo", "Mendoza", 5507),
    "guaymallen": _l("Guaymallén", "Mendoza", 5519),
    "tunuyan": _l("Tunuyán", "Mendoza", 5560),
    "malargue": _l("Malargüe", "Mendoza", 5613),
    "villa mercedes": _l("Villa Mercedes", "San Luis", 5730),
    "chilecito": _l("Chilecito", "La Rioja", 5360),
    # NOA
    "yerba buena": _l("Yerba Buena", "Tucumán", 4107, nombre_comun=True),
    "tafi viejo": _l("Tafí Viejo", "Tucumán", 4103),
    "oran": _l("San Ramón de la Nueva Orán", "Salta", 4530),
    "tartagal": _l("Tartagal", "Salta", 4560),
    "cafayate": _l("Cafayate", "Salta", 4427),
    "palpala": _l("Palpalá", "Jujuy", 4612),
    "humahuaca": _l("Humahuaca", "Jujuy", 4630),
    "tilcara": _l("Tilcara", "Jujuy", 4624),
    "la banda": _l("La Banda", "Santiago del Estero", 4300, nombre_comun=True),
    "termas de rio hondo": _l("Termas de Río Hondo", "Santiago del Estero", 4220),
    # NEA y Litoral
    "goya": _l("Goya", "Corrientes", 3450, nombre_comun=True),
    "paso de los libres": _l("Paso de los Libres", "Corrientes", 3230),
    "roque saenz peña": _l("Presidencia Roque Sáenz Peña", "Chaco", 3700),
    "presidencia roque saenz peña": _l("Presidencia Roque Sáenz Peña", "Chaco", 3700),
    "clorinda": _l("Clorinda", "Formosa", 3610, nombre_comun=True),
    "obera": _l("Oberá", "Misiones", 3360),
    "eldorado": _l("Eldorado", "Misiones", 3380),
    "puerto iguazu": _l("Puerto Iguazú", "Misiones", 3370),
    "iguazu": _l("Puerto Iguazú", "Misiones", 3370),
    "concordia": _l("Concordia", "Entre Ríos", 3200, nombre_comun=True),
    "gualeguaychu": _l("Gualeguaychú", "Entre Ríos", 2820),
    "concepcion del uruguay": _l("Concepción del Uruguay", "Entre Ríos", 3260),
    "gualeguay": _l("Gualeguay", "Entre Ríos", 2840),
    "villaguay": _l("Villaguay", "Entre Ríos", 3240),
    "chajari": _l("Chajarí", "Entre Ríos", 3228),
    # Patagonia
    "general pico": _l("General Pico", "La Pampa", 6360),
    "san martin de los andes": _l("San Martín de los Andes", "Neuquén", 8370),
    "zapala": _l("Zapala", "Neuquén", 8340),
    "plottier": _l("Plottier", "Neuquén", 8316),
    "cutral co": _l("Cutral Có", "Neuquén", 8322),
    "villa la angostura": _l("Villa La Angostura", "Neuquén", 8407),
    "general roca": _l("General Roca", "Río Negro", 8332),
    "bariloche": _l("San Carlos de Bariloche", "Río Negro", 8400),
    "san carlos de bariloche": _l("San Carlos de Bariloche", "Río Negro", 8400),
    "cipolletti": _l("Cipolletti", "Río Negro", 8324),
    "villa regina": _l("Villa Regina", "Río Negro", 8336),
    "el bolson": _l("El Bolsón", "Río Negro", 8430),
    "trelew": _l("Trelew", "Chubut", 9100),
    "comodoro rivadavia": _l("Comodoro Rivadavia", "Chubut", 9000),
    "comodoro": _l("Comodoro Rivadavia", "Chubut", 9000),
    "puerto madryn": _l("Puerto Madryn", "Chubut", 9120),
    "madryn": _l("Puerto Madryn", "Chubut", 9120),
    "esquel": _l("Esquel", "Chubut", 9200),
    "caleta olivia": _l("Caleta Olivia", "Santa Cruz", 9011),
    "el calafate": _l("El Calafate", "Santa Cruz", 9405),
    "calafate": _l("El Calafate", "Santa Cruz", 9405),
    "rio grande": _l("Río Grande", "Tierra del Fuego", 9420),
    # Nombres repetidos en varias provincias
    "san martin": LocalidadAmbigua("San Martín", ("San Martín (Buenos Aires)", "San Martín (Mendoza)")),
    "general san martin": LocalidadAmbigua("General San Martín", ()),
    "san miguel": LocalidadAmbigua("San Miguel", ("San Miguel (Buenos Aires)", "San Miguel de Tucumán")),
    "san pedro": LocalidadAmbigua("San Pedro", ("San Pedro (Buenos Aires)", "San Pedro de Jujuy")),
    "san justo": LocalidadAmbigua("San Justo", ("San Justo (Buenos Aires)", "San Justo (Santa Fe)")),
    "mercedes": LocalidadAmbigua("Mercedes", ("Mercedes (Buenos Aires)", "Mercedes (Corrientes)")),
    "merlo": LocalidadAmbigua("Merlo", ("Merlo (Buenos Aires)", "Merlo (San Luis)")),
    "san fernando": LocalidadAmbigua("San Fernando", ("San Fernando (Buenos Aires)", "Catamarca")),
    "villa nueva": LocalidadAmbigua("Villa Nueva", ("Villa Nueva (Córdoba)", "Villa Nueva (Mendoza)")),
    "maipu": LocalidadAmbigua("Maipú", ("Maipú (Mendoza)", "Maipú (Buenos Aires)")),
    "las heras": LocalidadAmbigua("Las Heras", ("Las Heras (Mendoza)", "Las Heras (Buenos Aires)")),
    "general alvear": LocalidadAmbigua("General Alvear", ("General Alvear (Mendoza)", "General Alvear (Buenos Aires)")),
    "concepcion": LocalidadAmbigua("Concepción", ("Concepción (Tucumán)", "Concepción del Uruguay")),
    "colon": LocalidadAmbigua("Colón", ("Colón (Entre Ríos)", "Colón (Buenos Aires)")),
    "victoria": LocalidadAmbigua("Victoria", ("Victoria (Entre Ríos)", "Victoria (Buenos Aires)")),
    "rivadavia": LocalidadAmbigua("Rivadavia", ()),
}

# Palabras de los nombres de localidades, para el corrector ortográfico.
PALABRAS_LOCALIDADES: set[str] = {palabra for clave in LOCALIDADES for palabra in clave.split()}
LARGO_MAXIMO = max(len(clave.split()) for clave in LOCALIDADES)


@dataclass(frozen=True)
class LocalidadEncontrada:
    texto: str  # cómo se escribió (normalizado)
    localidad: Localidad | LocalidadAmbigua
    inicio: int  # posición de la primera palabra
    fin: int  # posición siguiente a la última palabra

    @property
    def ambigua(self) -> bool:
        return isinstance(self.localidad, LocalidadAmbigua)


_PREPOSICIONES_DESTINO = {"a", "al", "hasta", "para", "hacia"}


def buscar_localidades(tokens: list[str], solo_inequivocas: bool = False) -> list[LocalidadEncontrada]:
    """Localidades nombradas en la secuencia de palabras (la coincidencia más larga primero).

    Con ``solo_inequivocas`` se omiten las ambiguas, las provincias y los nombres que también
    son palabras comunes (salvo después de «a», «hasta» o «para»: «¿y a Rosario?»); se usa
    cuando el mensaje no habla de envíos.
    """
    encontradas: list[LocalidadEncontrada] = []
    i = 0
    while i < len(tokens):
        for largo in range(min(LARGO_MAXIMO, len(tokens) - i), 0, -1):
            clave = " ".join(tokens[i : i + largo])
            localidad = LOCALIDADES.get(clave)
            if localidad is None:
                continue
            if solo_inequivocas:
                if isinstance(localidad, LocalidadAmbigua) or localidad.es_provincia:
                    continue
                if localidad.nombre_comun and not (i > 0 and tokens[i - 1] in _PREPOSICIONES_DESTINO):
                    continue
            encontradas.append(LocalidadEncontrada(clave, localidad, i, i + largo))
            i += largo
            break
        else:
            i += 1
    return encontradas
