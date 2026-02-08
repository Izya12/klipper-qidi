# OpenTag3D filament tag support
#
# Copyright (C) 2024
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

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
        logging.info("OpenTag3D: Updated tag data: %s" % (self.tag_data,))

        if self.auto_apply:
            self._apply_profile()

        rendered_gcode = self.on_tag_update_gcode.render()
        if rendered_gcode.strip():
            self.gcode.run_script(rendered_gcode)

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

    cmd_SET_OPENTAG3D_DATA_help = "Set OpenTag3D data for a reader"
    def cmd_SET_OPENTAG3D_DATA(self, gcmd):
        update_data = {}
        for key, gparam in [
            ('filament_material', 'MATERIAL'),
            ('filament_color', 'COLOR'),
            ('recommended_nozzle_temp', 'NOZZLE_TEMP'),
            ('recommended_bed_temp', 'BED_TEMP'),
            ('batch_id', 'BATCH_ID'),
            ('remaining_filament', 'REMAINING'),
        ]:
            if 'TEMP' in gparam or 'REMAINING' in gparam:
                val = gcmd.get_float(gparam, None)
            else:
                val = gcmd.get(gparam, None)
            
            if val is not None:
                update_data[key] = val

        if self.callback and update_data:
            self.callback(update_data)

def load_config(config):
    return OpenTag3D(config)

def load_config_prefix(config):
    return OpenTag3DReader(config)
