# OpenTag3D filament tag support
#
# Copyright (C) 2024
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import re

CORE_START_ADDR = 0x10
CORE_END_ADDR = 0x9F
CORE_LENGTH = CORE_END_ADDR - CORE_START_ADDR + 1

TAG_FORMAT_ADDR = 0x10
TAG_VERSION_ADDR = 0x12
MANUFACTURER_ADDR = 0x14
BASE_MATERIAL_ADDR = 0x24
MATERIAL_MODIFIERS_ADDR = 0x29
COLOR_NAME_ADDR = 0x2E
COLOR_1_ADDR = 0x4E
COLOR_2_ADDR = 0x52
COLOR_3_ADDR = 0x56
TARGET_DIAMETER_ADDR = 0x5A
TARGET_WEIGHT_ADDR = 0x5C
PRINT_TEMPERATURE_ADDR = 0x5E
BED_TEMPERATURE_ADDR = 0x5F
DENSITY_ADDR = 0x60
ONLINE_URL_ADDR = 0x6D

TAG_FORMAT_LEN = 2
TAG_VERSION_LEN = 2
MANUFACTURER_LEN = 16
BASE_MATERIAL_LEN = 5
MATERIAL_MODIFIERS_LEN = 5
COLOR_NAME_LEN = 32
COLOR_LEN = 4
TARGET_DIAMETER_LEN = 2
TARGET_WEIGHT_LEN = 2
PRINT_TEMPERATURE_LEN = 1
BED_TEMPERATURE_LEN = 1
DENSITY_LEN = 2
ONLINE_URL_LEN = 32

class OpenTag3D:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')

        self.reader_name = config.get('reader', None)
        self.auto_apply = config.getboolean('auto_apply_filament_profile', False)
        self.update_remaining = config.getboolean('update_remaining_filament',
                                                   False)

        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        self.on_tag_update_gcode = gcode_macro.load_template(
            config, 'on_tag_update_gcode', '')

        self.tag_data = {
            'tag_format': "",
            'tag_version': 0.0,
            'filament_manufacturer': "",
            'base_material': "",
            'material_modifiers': "",
            'color_name': "",
            'color_1_rgba': "",
            'color_2_rgba': "",
            'color_3_rgba': "",
            'target_diameter_um': 0,
            'target_weight_g': 0,
            'print_temperature': 0.0,
            'bed_temperature': 0.0,
            'density_g_cm3': 0.0,
            'online_data_url': "",
            'filament_material': "",
            'filament_color': "",
            'recommended_nozzle_temp': 0.0,
            'recommended_bed_temp': 0.0,
            'batch_id': "",
            'remaining_filament': 0.0,
        }

        self.reader = None
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

        self.gcode.register_command('OPENTAG3D_REFRESH',
                                    self.cmd_OPENTAG3D_REFRESH,
                                    desc=self.cmd_OPENTAG3D_REFRESH_help)
        self.gcode.register_command('OPENTAG3D_UPDATE_REMAINING',
                                    self.cmd_OPENTAG3D_UPDATE_REMAINING,
                                    desc=self.cmd_OPENTAG3D_UPDATE_REMAINING_help)

    def _handle_ready(self):
        if self.reader_name:
            try:
                reader_obj_name = self.reader_name
                # If it doesn't look like a full name, try with prefix
                if not any(prefix in reader_obj_name
                           for prefix in ["opentag3d_reader ", "mcu "]):
                    try:
                        test_obj = self.printer.lookup_object(reader_obj_name)
                    except self.printer.config_error:
                        reader_obj_name = "opentag3d_reader " + reader_obj_name

                self.reader = self.printer.lookup_object(reader_obj_name)
                if hasattr(self.reader, 'register_callback'):
                    self.reader.register_callback(self._tag_callback)
            except self.printer.config_error:
                logging.error("OpenTag3D: Reader '%s' not found" %
                              self.reader_name)

    def _tag_callback(self, tag_data):
        self.tag_data.update(tag_data)
        self._derive_tag_fields()
        logging.info("OpenTag3D: Updated tag data: %s" % (self.tag_data,))

        if self.auto_apply:
            self._apply_profile()

        rendered_gcode = self.on_tag_update_gcode.render()
        if rendered_gcode.strip():
            self.gcode.run_script(rendered_gcode)

    def _derive_tag_fields(self):
        base_material = self.tag_data.get('base_material', "")
        modifiers = self.tag_data.get('material_modifiers', "")
        if base_material and not self.tag_data.get('filament_material'):
            if modifiers:
                self.tag_data['filament_material'] = "%s %s" % (
                    base_material, modifiers)
            else:
                self.tag_data['filament_material'] = base_material

        if not self.tag_data.get('filament_color'):
            color_name = self.tag_data.get('color_name', "")
            if color_name:
                self.tag_data['filament_color'] = color_name
            else:
                color_hex = self.tag_data.get('color_1_rgba', "")
                if color_hex:
                    self.tag_data['filament_color'] = color_hex

        if not self.tag_data.get('recommended_nozzle_temp'):
            print_temp = self.tag_data.get('print_temperature')
            if print_temp:
                self.tag_data['recommended_nozzle_temp'] = print_temp

        if not self.tag_data.get('recommended_bed_temp'):
            bed_temp = self.tag_data.get('bed_temperature')
            if bed_temp:
                self.tag_data['recommended_bed_temp'] = bed_temp

    def _apply_profile(self):
        nozzle_temp = self.tag_data.get('recommended_nozzle_temp')
        bed_temp = self.tag_data.get('recommended_bed_temp')

        if nozzle_temp and nozzle_temp > 0:
            self.gcode.run_script(
                "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=%.2f"
                % nozzle_temp)
        if bed_temp and bed_temp > 0:
            self.gcode.run_script(
                "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=%.2f"
                % bed_temp)

    def get_status(self, eventtime):
        return self.tag_data

    cmd_OPENTAG3D_REFRESH_help = "Refresh OpenTag3D data from reader"
    def cmd_OPENTAG3D_REFRESH(self, gcmd):
        if self.reader and hasattr(self.reader, 'refresh'):
            self.reader.refresh()
            gcmd.respond_info("OpenTag3D: Refresh requested")
        else:
            gcmd.respond_info("OpenTag3D: Reader not available or "
                              "doesn't support refresh")

    cmd_OPENTAG3D_UPDATE_REMAINING_help = "Update remaining filament on tag"
    def cmd_OPENTAG3D_UPDATE_REMAINING(self, gcmd):
        remaining = gcmd.get_float('REMAINING')
        if self.reader and hasattr(self.reader, 'update_remaining'):
            self.reader.update_remaining(remaining)
            gcmd.respond_info("OpenTag3D: Update remaining requested")
        else:
            gcmd.respond_info("OpenTag3D: Reader doesn't support "
                              "updating remaining filament")

class OpenTag3DReader:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.callback = None
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_mux_command("SET_OPENTAG3D_DATA", "READER",
                                        self.name,
                                        self.cmd_SET_OPENTAG3D_DATA,
                                        desc=self.cmd_SET_OPENTAG3D_DATA_help)

    def register_callback(self, callback):
        self.callback = callback

    def refresh(self):
        self.printer.send_event("opentag3d:refresh", self.name)

    def update_remaining(self, remaining):
        self.printer.send_event("opentag3d:update_remaining",
                                self.name, remaining)

    def _decode_string(self, data, encoding):
        return data.split(b'\x00', 1)[0].decode(encoding, errors='ignore').strip()

    def _format_rgba(self, data):
        if len(data) != COLOR_LEN:
            return ""
        if all(byte == 0x00 for byte in data):
            return ""
        return "#%02X%02X%02X%02X" % tuple(data)

    def _parse_rgba_param(self, value):
        if value is None:
            return None
        hex_value = value.strip()
        if hex_value.startswith('#'):
            hex_value = hex_value[1:]
        if len(hex_value) == 6:
            hex_value += "FF"
        if len(hex_value) != 8 or not re.fullmatch(r"[0-9a-fA-F]{8}", hex_value):
            raise self.printer.command_error(
                "OpenTag3D: COLOR value must be 6 or 8 hex characters")
        return "#" + hex_value.upper()

    def _parse_raw_hex(self, raw_hex):
        hex_data = re.sub(r"[^0-9a-fA-F]", "", raw_hex or "")
        if not hex_data or len(hex_data) % 2:
            return None
        try:
            return bytes.fromhex(hex_data)
        except ValueError:
            return None

    def _parse_core_data(self, raw_data):
        if raw_data is None:
            return None
        if len(raw_data) >= CORE_START_ADDR + CORE_LENGTH:
            base_offset = 0
        elif len(raw_data) >= CORE_LENGTH:
            base_offset = -CORE_START_ADDR
        else:
            return None

        def _slice(addr, length):
            start = addr + base_offset
            end = start + length
            if start < 0 or end > len(raw_data):
                return b""
            return raw_data[start:end]

        tag_format = self._decode_string(
            _slice(TAG_FORMAT_ADDR, TAG_FORMAT_LEN), 'ascii')
        if tag_format and tag_format != "OT":
            return {'tag_format': tag_format, 'tag_version': 0.0}

        tag_version_raw = int.from_bytes(
            _slice(TAG_VERSION_ADDR, TAG_VERSION_LEN), 'big')
        manufacturer = self._decode_string(
            _slice(MANUFACTURER_ADDR, MANUFACTURER_LEN), 'utf-8')
        base_material = self._decode_string(
            _slice(BASE_MATERIAL_ADDR, BASE_MATERIAL_LEN), 'utf-8')
        material_modifiers = self._decode_string(
            _slice(MATERIAL_MODIFIERS_ADDR, MATERIAL_MODIFIERS_LEN), 'utf-8')
        color_name = self._decode_string(
            _slice(COLOR_NAME_ADDR, COLOR_NAME_LEN), 'utf-8')
        color_1_rgba = self._format_rgba(_slice(COLOR_1_ADDR, COLOR_LEN))
        color_2_rgba = self._format_rgba(_slice(COLOR_2_ADDR, COLOR_LEN))
        color_3_rgba = self._format_rgba(_slice(COLOR_3_ADDR, COLOR_LEN))
        target_diameter_um = int.from_bytes(
            _slice(TARGET_DIAMETER_ADDR, TARGET_DIAMETER_LEN), 'big')
        target_weight_g = int.from_bytes(
            _slice(TARGET_WEIGHT_ADDR, TARGET_WEIGHT_LEN), 'big')
        print_temp_raw = int.from_bytes(
            _slice(PRINT_TEMPERATURE_ADDR, PRINT_TEMPERATURE_LEN), 'big')
        bed_temp_raw = int.from_bytes(
            _slice(BED_TEMPERATURE_ADDR, BED_TEMPERATURE_LEN), 'big')
        density_raw = int.from_bytes(
            _slice(DENSITY_ADDR, DENSITY_LEN), 'big')
        online_url = self._decode_string(
            _slice(ONLINE_URL_ADDR, ONLINE_URL_LEN), 'ascii')

        print_temperature = float(print_temp_raw) * 5.0
        bed_temperature = float(bed_temp_raw) * 5.0
        density_g_cm3 = float(density_raw) / 1000.0 if density_raw else 0.0

        filament_material = base_material
        if base_material and material_modifiers:
            filament_material = "%s %s" % (base_material, material_modifiers)

        filament_color = color_name
        if not filament_color:
            filament_color = color_1_rgba

        return {
            'tag_format': tag_format,
            'tag_version': tag_version_raw / 1000.0,
            'filament_manufacturer': manufacturer,
            'base_material': base_material,
            'material_modifiers': material_modifiers,
            'color_name': color_name,
            'color_1_rgba': color_1_rgba,
            'color_2_rgba': color_2_rgba,
            'color_3_rgba': color_3_rgba,
            'target_diameter_um': target_diameter_um,
            'target_weight_g': target_weight_g,
            'print_temperature': print_temperature,
            'bed_temperature': bed_temperature,
            'density_g_cm3': density_g_cm3,
            'online_data_url': online_url,
            'filament_material': filament_material,
            'filament_color': filament_color,
            'recommended_nozzle_temp': print_temperature,
            'recommended_bed_temp': bed_temperature,
        }

    cmd_SET_OPENTAG3D_DATA_help = "Set OpenTag3D data for a reader"
    def cmd_SET_OPENTAG3D_DATA(self, gcmd):
        update_data = {}
        raw_hex = gcmd.get('RAW', None)
        if raw_hex:
            raw_data = self._parse_raw_hex(raw_hex)
            parsed = self._parse_core_data(raw_data)
            if parsed is None:
                raise self.printer.command_error(
                    "OpenTag3D: RAW data length is too short")
            if parsed.get('tag_format') != "OT":
                raise self.printer.command_error(
                    "OpenTag3D: RAW data is not OpenTag3D format")
            update_data.update(parsed)

        manual_fields = [
            ('tag_format', gcmd.get('TAG_FORMAT', None)),
            ('tag_version', gcmd.get_float('TAG_VERSION', None)),
            ('filament_manufacturer', gcmd.get('MANUFACTURER', None)),
            ('base_material', gcmd.get('BASE_MATERIAL', None)),
            ('material_modifiers', gcmd.get('MATERIAL_MODIFIERS', None)),
            ('color_name', gcmd.get('COLOR_NAME', None)),
            ('target_diameter_um', gcmd.get_int('DIAMETER_UM', None)),
            ('target_weight_g', gcmd.get_int('WEIGHT_G', None)),
            ('print_temperature', gcmd.get_float('PRINT_TEMP', None)),
            ('bed_temperature', gcmd.get_float('BED_TEMP', None)),
            ('density_g_cm3', gcmd.get_float('DENSITY', None)),
            ('online_data_url', gcmd.get('ONLINE_URL', None)),
            ('filament_material', gcmd.get('MATERIAL', None)),
            ('filament_color', gcmd.get('COLOR', None)),
            ('recommended_nozzle_temp', gcmd.get_float('NOZZLE_TEMP', None)),
            ('recommended_bed_temp', gcmd.get_float('RECOMMENDED_BED_TEMP', None)),
            ('batch_id', gcmd.get('BATCH_ID', None)),
            ('remaining_filament', gcmd.get_float('REMAINING', None)),
        ]

        color_1 = gcmd.get('COLOR_1', None)
        color_2 = gcmd.get('COLOR_2', None)
        color_3 = gcmd.get('COLOR_3', None)
        manual_colors = [
            ('color_1_rgba', self._parse_rgba_param(color_1)),
            ('color_2_rgba', self._parse_rgba_param(color_2)),
            ('color_3_rgba', self._parse_rgba_param(color_3)),
        ]

        for key, val in manual_fields + manual_colors:
            if val is not None:
                update_data[key] = val

        if self.callback and update_data:
            self.callback(update_data)


def load_config(config):
    return OpenTag3D(config)


def load_config_prefix(config):
    return OpenTag3DReader(config)
