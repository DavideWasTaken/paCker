"""Build wheels and self-contained sdists from canonical viewer/schema assets."""
from pathlib import Path
from shutil import copy2

import os

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
ASSETS = ('render.html', 'pose.js', 'packing-scene.js', 'camera.js',
          'vendor/three.module.js', 'vendor/three.core.js', 'vendor/LICENSE-three.txt')
SCHEMAS = ('request-v2.json', 'result-v2.json')


def copy_assets(destination):
    for directory, names, repository in (('assets', ASSETS, ROOT.parent / 'viewer'),
                                          ('schemas', SCHEMAS, ROOT.parent / 'schemas')):
        bundled = ROOT / 'packer_adapter' / directory
        source = bundled if bundled.is_dir() else repository
        for name in names:
            target = Path(destination) / 'packer_adapter' / directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            copy2(source / name, target)


class BuildWithAssets(build_py):
    def run(self):
        super().run()
        copy_assets(self.build_lib)


class SourceWithAssets(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        copy_assets(base_dir)


try:
    from setuptools.command.bdist_wheel import bdist_wheel
except ImportError:  # older setuptools
    from wheel.bdist_wheel import bdist_wheel


class PlatformWheel(bdist_wheel):
    """A wheel carrying packer3d/bin is tied to that executable's platform.

    PACKER3D_PLATFORM names the wheel platform tag, e.g. win_amd64 or
    manylinux2014_x86_64.musllinux_1_1_x86_64 for the static Linux build.
    Without a bundled executable the wheel stays pure Python.
    """
    def finalize_options(self):
        super().finalize_options()
        self.bundled = os.environ.get('PACKER3D_PLATFORM')
        if self.bundled:
            self.root_is_pure = False

    def get_tag(self):
        if self.bundled:
            return 'py3', 'none', self.bundled
        return super().get_tag()


setup(cmdclass={'build_py': BuildWithAssets, 'sdist': SourceWithAssets, 'bdist_wheel': PlatformWheel})
