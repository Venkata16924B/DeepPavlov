# Copyright 2017 Neural Networks and Deep Learning lab, MIPT
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from abc import ABCMeta, abstractmethod
from typing import List, Dict, Union, Tuple, Any

import numpy as np

from deeppavlov.core.common.registry import register


class Tracker(metaclass=ABCMeta):
    """
    An abstract class for trackers: a model that holds a dialogue state and
    generates state features.
    """

    @abstractmethod
    def update_state(self, slots: Union[List[Tuple[str, Any]], Dict[str, Any]]) -> 'Tracker':
        """
        Updates dialogue state with new ``slots``, calculates features.

        Returns:
            Tracker: ."""
        pass

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """
        Returns:
            Dict[str, Any]: dictionary with current slots and their values."""
        pass

    @abstractmethod
    def reset_state(self) -> None:
        """Resets dialogue state"""
        pass

    @abstractmethod
    def get_features(self) -> np.ndarray:
        """
        Returns:
            np.ndarray[float]: numpy array with calculates state features."""
        pass


class DefaultTracker(Tracker):
    """
    Tracker that overwrites slots with new values.
    Features are binary indicators: slot is present/absent.

    Parameters:
        slot_names: list of slots that should be tracked.
    """

    def __init__(self, slot_names: List[str]) -> None:
        self.slot_names = list(slot_names)
        self.history = []
        self.curr_feats = np.zeros(len(self.slot_names), dtype=np.float32)

    @property
    def state_size(self):
        return len(self.slot_names)

    @property
    def num_features(self):
        return self.state_size

    def update_state(self, slots):
        if isinstance(slots, list):
            self.history.extend(self._filter(slots))

        elif isinstance(slots, dict):
            for slot, value in self._filter(slots.items()):
                self.history.append((slot, value))

        self.curr_feats = self._binary_features()
        return self

    def get_state(self):
        lasts = {}
        for slot, value in self.history:
            lasts[slot] = value
        return lasts

    def reset_state(self):
        self.history = []
        self.curr_feats = np.zeros(self.state_size, dtype=np.float32)

    def get_features(self):
        return self.curr_feats

    def _filter(self, slots):
        return filter(lambda s: s[0] in self.slot_names, slots)

    def _binary_features(self):
        feats = np.zeros(self.state_size, dtype=np.float32)
        lasts = self.get_state()
        for i, slot in enumerate(self.slot_names):
            if slot in lasts:
                feats[i] = 1.
        return feats


@register('featurized_tracker')
class FeaturizedTracker(DefaultTracker):
    """
    Tracker that overwrites slots with new values.
    Features are binary features (slot is present/absent) plus difference features
    (slot value is (the same)/(not the same) as before last update) and count
    features (sum of present slots and sum of changed during last update slots).

    Parameters:
        slot_names: list of slots that should be tracked.
    """
    @property
    def num_features(self):
        return self.state_size * 3 + 3

    def update_state(self, slots):
        super().update_state(slots)
        bin_feats = self.curr_feats

        prev_state = self.get_state()
        diff_feats = self._diff_features(prev_state)
        new_feats = self._new_features(prev_state)
        self.curr_feats = np.hstack((
            bin_feats,
            diff_feats,
            new_feats,
            np.sum(bin_feats),
            np.sum(diff_feats),
            np.sum(new_feats))
        )
        return self

    def _diff_features(self, state):
        feats = np.zeros(self.state_size, dtype=np.float32)
        curr_state = self.get_state()

        for i, slot in enumerate(self.slot_names):
            if slot in curr_state and slot in state and curr_state[slot] != state[slot]:
                feats[i] = 1.

        return feats

    def _new_features(self, state):
        feats = np.zeros(self.state_size, dtype=np.float32)
        curr_state = self.get_state()

        for i, slot in enumerate(self.slot_names):
            if slot in curr_state and slot not in state:
                feats[i] = 1.

        return feats


class DialogueStateTracker(Tracker):
    def __init__(self, tracker, n_actions: int, hidden_size: int):
        self.tracker = tracker
        self.db_result = None
        self.current_db_result = None

        self.n_actions = n_actions
        self.hidden_size = hidden_size
        self.prev_action = np.zeros(n_actions, dtype=np.float32)

        self.network_state = (
            np.zeros([1, hidden_size], dtype=np.float32),
            np.zeros([1, hidden_size], dtype=np.float32)
        )

    @property
    def state_size(self):
        return self.tracker.state_size

    @property
    def num_features(self):
        return self.tracker.num_features

    def update_state(self, slots):
        self.tracker.update_state(slots)

    def reset_state(self):
        self.tracker.reset_state()
        self.db_result = None
        self.current_db_result = None
        self.prev_action = np.zeros(self.n_actions, dtype=np.float32)

        self.network_state = (
            np.zeros([1, self.hidden_size], dtype=np.float32),
            np.zeros([1, self.hidden_size], dtype=np.float32)
        )

    def get_state(self):
        return self.tracker.get_state()

    def get_features(self):
        return self.tracker.get_features()


class MultipleUserStateTracker(object):
    def __init__(self):
        self._ids_to_trackers = {}

    def check_new_user(self, user_id):
        return user_id in self._ids_to_trackers

    def init_new_tracker(self, user_id, tracker_class=DialogueStateTracker, **init_params):
        self._ids_to_trackers[user_id] = tracker_class(**init_params)
