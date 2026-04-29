from Prism_AssetLibrary_Variables import Prism_AssetLibrary_Variables
from Prism_AssetLibrary_Functions import Prism_AssetLibrary_Functions


class Prism_AssetLibrary(Prism_AssetLibrary_Variables, Prism_AssetLibrary_Functions):
    def __init__(self, core):
        Prism_AssetLibrary_Variables.__init__(self, core, self)
        Prism_AssetLibrary_Functions.__init__(self, core, self)
