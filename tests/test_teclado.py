import sys
import unittest
from unittest.mock import Mock, patch

import main


class TecladoTest(unittest.TestCase):
    def test_a_toggles_without_enter_and_extended_keys_are_ignored(self):
        keyboard = Mock()
        keyboard.kbhit.return_value = True
        keyboard.getwch.side_effect = ['a', '\xe0', 'A', 'A', 'x']
        encerrar = Mock()
        encerrar.wait.side_effect = [False, False, False, False, True]
        with patch.dict(sys.modules, msvcrt=keyboard), \
             patch.object(main, 'alternar_modo_ausente') as toggle:
            main.teclado_texto(encerrar)
        self.assertEqual(toggle.call_count, 2)
