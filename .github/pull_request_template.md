## Related issue

<!-- "Closes #123", or say why this needs no issue. -->

## Summary

<!-- What changes and why, in a paragraph. Lead with the behavior a user or reviewer sees. -->

## Scope

<!-- Files and subsystems touched, plus anything nearby you deliberately left alone.
     Leave your commit history as it is. The merge squashes it. -->

## Validation

<!-- Paste the command you ran and its last lines. The functional gate is:

```
docker build -t tvc-dev docker/
docker run --rm -v "$PWD":/w -w /w --cap-add=IPC_LOCK \
  --ulimit memlock=-1:-1 tvc-dev bash tests/ci.sh
```
CI runs the same gate on a hosted `ubuntu-latest` runner, which proves the code
works and proves nothing about timing. CONTRIBUTING.md covers running the tests. -->

## Evidence and claims

<!-- A timing number needs a qualified run behind it: machine, configuration, cycle count.
     Write "no new claims" if there are none. Corrupting or mislabeling a measurement is a
     critical defect, so say how you ruled that out. -->

## Known limitations

<!-- What still does not work after this. The vehicle model, the controller, impaired sensor
     and actuator links, episode semantics, and the Python ground station are not implemented. -->

## Checklist

- [ ] Nontrivial work links an issue.
- [ ] The change stays focused. No unrelated cleanup rides along.
- [ ] The functional gate passed in the container.
- [ ] The gate's ASan, UBSan, and TSan trees came back green.
- [ ] Public documentation changed only where public behavior changed.
- [ ] No internal planning or design document added or linked.
- [ ] No new timing or performance claim, or qualified evidence is attached.
- [ ] Any new dependency was accepted in a proposal issue, and the summary says why.
- [ ] Known limitations stated above.
- [ ] No agent or tool attribution section added.
