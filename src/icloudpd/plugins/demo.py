"""Demo plugin showing hook usage with instance variable accumulation

This plugin demonstrates:
1. Using instance variables to accumulate data across hook calls
2. Reporting accumulated data in on_download_all_sizes_complete
3. Clearing accumulator after each photo
4. Showing what context is available at each hook point
"""

from argparse import ArgumentParser, Namespace
from typing import List, Dict, Any

from icloudpd.plugins.base import IcloudpdPlugin
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import VersionSize


class DemoPlugin(IcloudpdPlugin):
    """Demo plugin showing hook context and accumulator pattern.
    
    This plugin doesn't do anything useful - it demonstrates:
    - What data is available at each hook point
    - How to use instance variables to accumulate data
    - When to process and clear accumulated data
    
    Example:
        $ icloudpd --plugin demo --recent 5
        $ icloudpd --plugin demo --demo-verbose --recent 5
        $ icloudpd --plugin demo --demo-compact --recent 100
    """
    
    def __init__(self):
        """Initialize demo plugin with accumulators"""
        self.verbose = False
        self.compact = False
        
        # Accumulators for current photo being processed
        self.current_photo_files: List[Dict[str, Any]] = []
        self.current_photo_id: str = ""
        
        # Global counters for the run
        self.total_photos = 0
        self.total_files_downloaded = 0
        self.total_files_existed = 0
        self.total_files_live = 0
    
    @property
    def name(self) -> str:
        """Plugin name"""
        return "demo"
    
    @property
    def version(self) -> str:
        """Plugin version"""
        return "1.0.0"
    
    @property
    def description(self) -> str:
        """Plugin description"""
        return "Demo plugin showing hook context (development tool)"
    
    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add demo plugin CLI arguments"""
        group = parser.add_argument_group('Demo Plugin Options')
        group.add_argument(
            '--demo-verbose',
            action='store_true',
            help='Show full metadata in hook output (very detailed)'
        )
        group.add_argument(
            '--demo-compact',
            action='store_true',
            help='Show compact one-line output per photo'
        )
    
    def configure(self, config: Namespace) -> None:
        """Configure demo plugin from CLI arguments"""
        self.verbose = getattr(config, 'demo_verbose', False)
        self.compact = getattr(config, 'demo_compact', False)
        
        if not self.compact:
            print("\n" + "=" * 70)
            print("🔌 Demo Plugin: Initialized")
            print("=" * 70)
            print(f"   Version:     {self.version}")
            print(f"   Verbose:     {self.verbose}")
            print(f"   Compact:     {self.compact}")
            print("=" * 70)
            print("\nThis plugin shows data available at each hook point.")
            print("It accumulates files in instance variables, then reports")
            print("when all sizes are complete.\n")
    
    # ========================================================================
    # PER-SIZE HOOKS - Accumulate data
    # ========================================================================
    
    def on_download_exists(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """File already exists - add to accumulator"""
        if not self.compact and not self.verbose:
            print(f"   📂 Exists:     {download_size.value:>11} - {download_path}")
        
        # Accumulate
        self.current_photo_files.append({
            'status': 'existed',
            'path': download_path,
            'size': download_size.value,
            'is_live': False,
        })
        self.total_files_existed += 1
    
    def on_download_downloaded(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """File was downloaded - add to accumulator"""
        if not self.compact and not self.verbose:
            print(f"   ⬇️  Downloaded: {download_size.value:>11} - {download_path}")
        
        # Accumulate
        self.current_photo_files.append({
            'status': 'downloaded',
            'path': download_path,
            'size': download_size.value,
            'is_live': False,
        })
        self.total_files_downloaded += 1
    
    def on_download_complete(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Size processing complete - accumulate if not already accumulated.
        
        This hook ALWAYS runs, so we use it to ensure files are tracked
        even if they didn't go through exists or downloaded hooks.
        """
        # Check if this file was already accumulated
        already_accumulated = any(
            f['path'] == download_path for f in self.current_photo_files
        )
        
        # If not accumulated yet (edge case), add it now
        if not already_accumulated:
            self.current_photo_files.append({
                'status': 'complete',
                'path': download_path,
                'size': download_size.value,
                'is_live': False,
            })
        
        if self.verbose:
            print(f"   ✅ Complete:   {download_size.value:>11} - {download_path}")
    
    # ========================================================================
    # LIVE PHOTO HOOKS - Accumulate live photo data
    # ========================================================================
    
    def on_download_exists_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Live photo exists - add to accumulator"""
        if not self.compact and not self.verbose:
            print(f"   📂 Exists:     {download_size.value:>11} - {download_path} 🎥")
        
        # Accumulate
        self.current_photo_files.append({
            'status': 'existed',
            'path': download_path,
            'size': download_size.value,
            'is_live': True,
        })
        self.total_files_existed += 1
        self.total_files_live += 1
    
    def on_download_downloaded_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Live photo downloaded - add to accumulator"""
        if not self.compact and not self.verbose:
            print(f"   ⬇️  Downloaded: {download_size.value:>11} - {download_path} 🎥")
        
        # Accumulate
        self.current_photo_files.append({
            'status': 'downloaded',
            'path': download_path,
            'size': download_size.value,
            'is_live': True,
        })
        self.total_files_downloaded += 1
        self.total_files_live += 1
    
    def on_download_complete_live(
        self,
        download_path: str,
        photo_filename: str,
        download_size: VersionSize,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """Live photo processing complete"""
        # Check if already accumulated
        already_accumulated = any(
            f['path'] == download_path for f in self.current_photo_files
        )
        
        if not already_accumulated:
            self.current_photo_files.append({
                'status': 'complete',
                'path': download_path,
                'size': download_size.value,
                'is_live': True,
            })
            self.total_files_live += 1
        
        if self.verbose:
            print(f"   ✅ Complete:   {download_size.value:>11} - {download_path} 🎥")
    
    # ========================================================================
    # KEY HOOK - Process accumulated data and clear
    # ========================================================================
    
    def on_download_all_sizes_complete(
        self,
        photo: PhotoAsset,
        dry_run: bool,
    ) -> None:
        """ALL sizes complete - process accumulated data and clear.
        
        This is where you would:
        - Upload all accumulated files to a service
        - Stack size variants together
        - Add to albums
        - Generate reports
        """
        self.total_photos += 1
        
        if self.compact:
            # Compact mode: one line per photo
            downloaded = sum(1 for f in self.current_photo_files if f['status'] == 'downloaded')
            existed = sum(1 for f in self.current_photo_files if f['status'] == 'existed')
            sizes = ','.join(set(f['size'] for f in self.current_photo_files))
            
            # Check if favorite
            is_fav = photo._asset_record.get("fields", {}).get("isFavorite", {}).get("value") == 1
            fav_marker = "⭐" if is_fav else "  "
            
            print(f"{fav_marker} {photo.filename} [{sizes}] (↓{downloaded} ✓{existed})")
        else:
            # Full mode: detailed output
            print("\n" + "=" * 70)
            print(f"📸 PHOTO COMPLETE: {photo.filename} (#{self.total_photos})")
            print("=" * 70)
            
            # Photo info
            is_fav = photo._asset_record.get("fields", {}).get("isFavorite", {}).get("value") == 1
            print(f"\n📋 Photo Information:")
            print(f"   ID:         {photo.id}")
            print(f"   Filename:   {photo.filename}")
            print(f"   Favorite:   {'⭐ YES' if is_fav else 'No'}")
            
            if self.verbose:
                print(f"   Created:    {photo.created}")
                print(f"   Size:       {photo.size:,} bytes")
                if hasattr(photo, 'dimensions'):
                    print(f"   Dimensions: {photo.dimensions}")
            
            # Accumulated files
            print(f"\n📁 Processed Files ({len(self.current_photo_files)}):")
            for i, file_info in enumerate(self.current_photo_files, 1):
                status_icon = "⬇️" if file_info['status'] == 'downloaded' else "📂"
                live_icon = " 🎥" if file_info['is_live'] else ""
                print(f"   {status_icon} {i}. [{file_info['size']:>11}]{live_icon}")
                if self.verbose:
                    print(f"       {file_info['path']}")
            
            # What a real plugin would do
            print(f"\n💡 What a Real Plugin Would Do Here:")
            print(f"   • Upload {len(self.current_photo_files)} file(s) to cloud storage")
            if len(self.current_photo_files) > 1:
                print(f"   • Stack/group the {len(self.current_photo_files)} variants together")
            if is_fav:
                print(f"   • Mark as favorite in the service")
            print(f"   • Add to album based on date or tags")
            print()
        
        # IMPORTANT: Clear accumulator for next photo
        self.current_photo_files.clear()
    
    # ========================================================================
    # RUN COMPLETE - Final summary
    # ========================================================================
    
    def on_run_completed(
        self,
        dry_run: bool,
    ) -> None:
        """Run complete - show final summary"""
        if self.compact:
            print(f"\n✅ Complete: {self.total_photos} photos, {self.total_files_downloaded + self.total_files_existed} files")
        else:
            print("\n" + "=" * 70)
            print("✅ RUN COMPLETED")
            print("=" * 70)
            print(f"\n📊 Final Statistics:")
            print(f"   Total Photos:         {self.total_photos}")
            print(f"   Files Downloaded:     {self.total_files_downloaded}")
            print(f"   Files Already Existed: {self.total_files_existed}")
            print(f"   Live Photos:          {self.total_files_live}")
            print(f"   Total Files:          {self.total_files_downloaded + self.total_files_existed}")
            
            print(f"\n💡 What a Real Plugin Would Do:")
            print(f"   • Upload summary to service dashboard")
            print(f"   • Send completion notification")
            print(f"   • Trigger backup or sync processes")
            print(f"   • Clean up temporary files")
            print("=" * 70)
            print()
    
    def cleanup(self) -> None:
        """Cleanup called on shutdown"""
        if not self.compact and self.verbose:
            print("\n🔌 Demo Plugin: Cleanup called")
