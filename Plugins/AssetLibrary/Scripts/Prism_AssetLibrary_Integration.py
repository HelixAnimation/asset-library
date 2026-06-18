import os
import shutil


class Prism_AssetLibrary_Integration(object):
    def __init__(self, core, plugin):
        self.core = core
        self.plugin = plugin

    def addIntegration(self, installPath):
        try:
            pkg_dir = os.path.join(installPath, "packages")
            if not os.path.exists(pkg_dir):
                os.makedirs(pkg_dir)

            pkg_dst = os.path.join(pkg_dir, "AssetLibrary.json")
            template = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "Integration", "AssetLibrary.json"
            )

            with open(template, "r") as f:
                content = f.read()

            plugin_root = self.plugin.pluginDirectory.replace("\\", "/")
            content = content.replace("PLUGINROOT", plugin_root)

            with open(pkg_dst, "w") as f:
                f.write(content)

            return True
        except Exception as e:
            self.core.popup("AssetLibrary: failed to write Houdini package:\n%s" % e)
            return False

    def removeIntegration(self, installPath):
        try:
            pkg_dst = os.path.join(installPath, "packages", "AssetLibrary.json")
            if os.path.exists(pkg_dst):
                os.remove(pkg_dst)
            return True
        except Exception as e:
            self.core.popup("AssetLibrary: failed to remove Houdini package:\n%s" % e)
            return False
