import os


class Prism_AssetLibrary_Variables(object):
    def __init__(self, core, plugin):
        self.version = "v0.1.0"
        self.pluginName = "AssetLibrary"
        self.pluginType = "Custom"
        self.platforms = ["Windows", "Linux", "Darwin"]
        self.pluginDirectory = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
