#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from PIL import Image

def main():
    if len(sys.argv) < 2:
        print("Usage: python png2icns.py <input.png> [output.icns]")
        sys.exit(1)
        
    input_file = sys.argv[1]
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        output_file = os.path.splitext(input_file)[0] + ".icns"
        
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        sys.exit(1)
        
    try:
        img = Image.open(input_file)
        # Ensure it's RGBA for proper transparency support in icon
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        # Resize to 512x512 as it's standard maximum size for basic ICNS (will auto generate smaller sizes inside format)
        img = img.resize((512, 512), Image.Resampling.LANCZOS)
        img.save(output_file, format='ICNS')
        print(f"Successfully converted {input_file} to {output_file}")
    except Exception as e:
        print(f"Failed to convert: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
