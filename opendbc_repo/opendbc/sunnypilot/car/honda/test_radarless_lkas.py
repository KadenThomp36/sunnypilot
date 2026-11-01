"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import unittest

from opendbc.can import CANParser
from opendbc.car import structs
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR, CruiseButtons, CruiseSettings

SCM_BUTTONS = 0x296


class TestRadarlessStockLkasProxy(unittest.TestCase):
  """While engaged on radarless, openpilot proxies SCM_BUTTONS to the camera so stock LKAS stays off."""

  def setUp(self):
    CarInterface = interfaces[CAR.HONDA_CIVIC_2022]
    CP = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC_2022)
    CP_SP = CarInterface.get_non_essential_params_sp(CP, CAR.HONDA_CIVIC_2022)
    self.CI = CarInterface(CP, CP_SP)
    self.CS = self.CI.CS
    self.CS.lkas_hud = {"LKAS_READY": 0, "LKAS_PROBLEM": 0}
    self.CS.cruise_setting = 0
    self.CS.cruise_buttons = 0
    self.parser = CANParser("honda_bosch_radarless_generated", [("SCM_BUTTONS", 0)], 2)

  def _step(self, enabled: bool, mads: bool = False):
    CC = structs.CarControl.new_message(enabled=enabled, latActive=enabled or mads).as_reader()
    CC_SP = structs.CarControlSP()
    CC_SP.mads.enabled = mads
    _, sends = self.CI.apply(CC, CC_SP)
    return [s for s in sends if s[0] == SCM_BUTTONS]

  def _decode(self, msg):
    self.parser.update([(0, [msg])])
    return self.parser.vl["SCM_BUTTONS"]["CRUISE_BUTTONS"], self.parser.vl["SCM_BUTTONS"]["CRUISE_SETTING"]

  def _run(self, frames, enabled=True, mads=False):
    return [m for _ in range(frames) for m in self._step(enabled, mads)]

  def test_nothing_sent_when_disengaged(self):
    self.CS.lkas_hud["LKAS_READY"] = 1
    self.assertEqual(self._run(400, enabled=False), [])

  def test_mads_lateral_only(self):
    # MADS lateral with ACC off (e.g. LKAS button pressed while driving manually): stock LKAS's nag would block
    # engaging ACC, so proxy and keep stock LKAS off here too
    self.CS.lkas_hud["LKAS_READY"] = 1
    settings = [self._decode(m)[1] for m in self._run(100, enabled=False, mads=True)]
    self.assertEqual(len(settings), 25)
    self.assertEqual(settings[:3], [CruiseSettings.LKAS] * 3)

    # the driver's SET still reaches the camera
    self.CS.lkas_hud["LKAS_READY"] = 0
    self.CS.cruise_buttons = CruiseButtons.DECEL_SET
    self.assertEqual(self._decode(self._run(4, enabled=False, mads=True)[-1]), (CruiseButtons.DECEL_SET, 0))

  def test_proxies_at_25hz_on_camera_bus(self):
    msgs = self._run(100)
    self.assertEqual(len(msgs), 25)
    self.assertTrue(all(m[2] == 2 for m in msgs))

  def test_driver_buttons_pass_through(self):
    for button, setting in ((CruiseButtons.RES_ACCEL, 0), (CruiseButtons.DECEL_SET, 0), (0, CruiseSettings.DISTANCE)):
      self.CS.cruise_buttons, self.CS.cruise_setting = button, setting
      self.assertEqual(self._decode(self._run(4)[-1]), (button, setting))

  def test_driver_lkas_press_blocked(self):
    self.CS.cruise_setting = CruiseSettings.LKAS
    self.assertTrue(all(self._decode(m)[1] == 0 for m in self._run(100)))

  def test_turns_off_stock_lkas(self):
    self.CS.lkas_hud["LKAS_READY"] = 1
    settings = [self._decode(m)[1] for m in self._run(100)]
    # one ~120 ms LKAS press, then released
    self.assertEqual(settings[:3], [CruiseSettings.LKAS] * 3)
    self.assertTrue(all(s == 0 for s in settings[3:]))

    # still on 5 s after the last press (it was missed): press again, but no sooner
    settings = [self._decode(m)[1] for m in self._run(420)]
    self.assertEqual(settings.count(CruiseSettings.LKAS), 3)
    self.assertEqual(settings[-3:], [CruiseSettings.LKAS] * 3)

    # camera reports stock LKAS off: no more presses
    self.CS.lkas_hud["LKAS_READY"] = 0
    settings = [self._decode(m)[1] for m in self._run(1000)]
    self.assertNotIn(CruiseSettings.LKAS, settings)


if __name__ == "__main__":
  unittest.main()
