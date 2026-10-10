"""paCker cuboid packing for Python: the native engine ships inside the wheel.

    from packer3d import Packer
    result = (Packer().add_box(id='carton', width=180, length=180, height=30)
              .add_item(id='bar', width=220, length=30, height=20, quantity=3).pack())
"""
from packer_adapter.client import Packer, PackerError, default_binary

__version__ = '0.5.0'
__all__ = ['Packer', 'PackerError', 'default_binary', '__version__']
