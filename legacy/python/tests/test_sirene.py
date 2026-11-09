import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sirene import Sirene


class SireneTest(unittest.TestCase):
    def run_pulse(self, send_error=None, devices=None):
        messages = []
        done = threading.Event()
        def informar(message):
            messages.append(message)
            if 'desligada' in message or 'falha' in message:
                done.set()
        stop = Mock()
        stop.is_set.return_value = False
        def wait(seconds):
            self.assertEqual(seconds, 5)
            return False
        stop.wait.side_effect = wait
        devices = devices if devices is not None else [SimpleNamespace(device='COM7', vid=0x1A86, pid=0x7523)]
        with patch('relay_usb.list_ports.comports', return_value=devices), \
             patch('sirene.serial.Serial') as serial, \
             patch('sirene.send', side_effect=send_error) as send:
            controller = Sirene(informar)
            # Replace only the pulse wait; the queue keeps the worker idle until requested.
            controller.parar = stop
            controller.acionar()
            self.assertTrue(done.wait(2))
            stop.is_set.return_value = True
            controller.worker.join(2)
            self.assertFalse(controller.worker.is_alive())
            return messages, serial, send

    def test_pulse_waits_five_seconds_and_switches_off(self):
        messages, serial, send = self.run_pulse()
        self.assertEqual([call.args[1] for call in send.call_args_list], [True, False])
        self.assertIn('desligada', messages[-1])

    def test_failed_on_still_attempts_off(self):
        messages, serial, send = self.run_pulse(send_error=[OSError('USB'), None])
        self.assertEqual([call.args[1] for call in send.call_args_list], [True, False])
        self.assertIn('falha', messages[-1])

    def test_missing_device_does_not_open_other_port(self):
        messages, serial, send = self.run_pulse(devices=[])
        serial.assert_not_called()
        send.assert_not_called()
        self.assertIn('falha', messages[-1])

    def test_multiple_matching_devices_are_rejected(self):
        devices = [SimpleNamespace(device=port, vid=0x1A86, pid=0x7523)
                   for port in ('COM7', 'COM9')]
        messages, serial, send = self.run_pulse(devices=devices)
        serial.assert_not_called()
        self.assertIn('Mais de um', messages[-1])

    def test_redetects_after_usb_port_change_without_restart(self):
        done = threading.Event()
        def informar(message):
            if 'desligada' in message or 'falha' in message:
                done.set()
        device = lambda port: SimpleNamespace(device=port, vid=0x1A86, pid=0x7523)
        unrelated = SimpleNamespace(device='COM5', vid=None, pid=None)
        with patch('relay_usb.list_ports.comports', side_effect=[
                [unrelated, device('COM7')], [], [unrelated, device('COM12')]]), \
             patch('sirene.serial.Serial') as serial, patch('sirene.send'):
            controller = Sirene(informar)
            self.addCleanup(controller.close)
            with patch.object(controller.parar, 'wait', return_value=False):
                for _ in range(3):
                    done.clear()
                    controller.acionar()
                    self.assertTrue(done.wait(2))
            controller.close()
        self.assertEqual([call.args[0] for call in serial.call_args_list], ['COM7', 'COM12'])

    def test_close_interrupts_active_pulse_and_sends_off(self):
        active = threading.Event()
        def informar(message):
            if 'acionada' in message:
                active.set()
        device = SimpleNamespace(device='COM7', vid=0x1A86, pid=0x7523)
        with patch('relay_usb.list_ports.comports', return_value=[device]), \
             patch('sirene.serial.Serial'), patch('sirene.send') as send:
            controller = Sirene(informar)
            controller.acionar()
            self.assertTrue(active.wait(2))
            controller.close()
            self.assertEqual([call.args[1] for call in send.call_args_list], [True, False])


if __name__ == '__main__':
    unittest.main()
