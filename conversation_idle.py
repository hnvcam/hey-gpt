"""Count idle only from fresh, explicit browser UI idle observations."""
class ConversationIdle:
    def __init__(self, freshness=4.):
        self.freshness=freshness
        self.reset()

    def reset(self):
        self.state='unknown'
        self.updated=None
        self.idle_since=None

    def update(self,state,now):
        if state not in {'idle','busy','unknown'}:
            return
        continuous=(self.state=='idle' and self.updated is not None
                    and 0<=now-self.updated<=self.freshness)
        if state=='idle':
            if not continuous or self.idle_since is None:self.idle_since=now
        else:
            self.idle_since=None
        self.state,self.updated=state,now

    def remaining(self,now,last_local,seconds):
        if (seconds<=0 or self.state!='idle' or self.updated is None
                or not 0<=now-self.updated<=self.freshness or self.idle_since is None):
            return None
        return max(0.,seconds-(now-max(self.idle_since,last_local)))

    def state_at(self,now):
        return self.state if self.updated is not None and 0<=now-self.updated<=self.freshness else 'unknown'

    def expired(self,now,last_local,seconds):
        return self.remaining(now,last_local,seconds)==0
