def classFactory(iface):
    from .plugin import CostPathPlugin

    return CostPathPlugin(iface)

