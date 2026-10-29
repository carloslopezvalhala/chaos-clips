"""Visual templates: a layout + a caption style + a hook style."""

LAYOUTS = {
    "fill": "Pantalla completa (recorta siguiendo la cara)",
    "A": "Pantalla partida (plano entero + zoom a la cara)",
    "B": "Plano entero sobre fondo desenfocado",
    "podcast": "Podcast (dos caras, una arriba y otra abajo)",
    "auto": "Automático (partida si hay cara, si no desenfocado)",
}

SUB_STYLES = {
    "karaoke": "Karaoke amarillo (3 palabras, la que suena en amarillo)",
    "hormozi": "Hormozi (2 palabras, verde y amarillo)",
    "pop": "Pop (una palabra gigante cada vez)",
    "caja": "Caja negra (frases cortas sobre fondo negro)",
    "minimal": "Minimalista (minúsculas, sin colores)",
}

HOOK_STYLES = {
    "caja_blanca": "Caja blanca, texto negro",
    "caja_negra": "Caja negra, texto blanco",
    "amarillo": "Texto amarillo grande",
    "ninguno": "Sin hook",
}

PRESETS = {
    "viral": {"name": "Clásico viral", "layout": "fill", "subs": "hormozi", "hook": "amarillo"},
    "karaoke": {"name": "Karaoke amarillo", "layout": "fill", "subs": "karaoke", "hook": "caja_blanca"},
    "partida": {"name": "Pantalla partida", "layout": "A", "subs": "karaoke", "hook": "caja_blanca"},
    "podcast": {"name": "Podcast dos caras", "layout": "podcast", "subs": "hormozi", "hook": "caja_negra"},
    "pop": {"name": "Pop palabra a palabra", "layout": "fill", "subs": "pop", "hook": "ninguno"},
    "desenfocado": {"name": "Fondo desenfocado", "layout": "B", "subs": "caja", "hook": "caja_blanca"},
    "minimal": {"name": "Minimalista", "layout": "fill", "subs": "minimal", "hook": "ninguno"},
    "hormozi": {"name": "Estilo Hormozi", "layout": "fill", "subs": "hormozi", "hook": "caja_negra"},
    "documental": {"name": "Documental", "layout": "B", "subs": "minimal", "hook": "caja_negra"},
    "gaming": {"name": "Gaming / streamer", "layout": "A", "subs": "pop", "hook": "amarillo"},
    "favorited": {"name": "Favorited (directo)", "layout": "auto", "subs": "karaoke", "hook": "caja_blanca"},
}


def parse(spec):
    """'viral' (preset key) or 'layout:subs:hook' -> template dict."""
    if spec in PRESETS:
        return dict(PRESETS[spec])
    layout, subs, hook = (spec.split(":") + ["", "", ""])[:3]
    return {"name": "Personalizada", "layout": layout if layout in LAYOUTS else "fill",
            "subs": subs if subs in SUB_STYLES else "karaoke",
            "hook": hook if hook in HOOK_STYLES else "caja_blanca"}


def spec_of(tpl):
    return f"{tpl['layout']}:{tpl['subs']}:{tpl['hook']}"
