import {expect} from '@playwright/test';

// Compare rendered edges with the available content area, so a cropped card
// screenshot cannot hide unused space elsewhere in the workspace.
export async function expectFullWidth(locator, containerSelector) {
  await expect.poll(()=>locator.evaluate((element,selector)=>{
    const container=element.parentElement.closest(selector);
    const outer=container.getBoundingClientRect(),inner=element.getBoundingClientRect();
    const style=getComputedStyle(container);
    const left=outer.left+parseFloat(style.borderLeftWidth)+parseFloat(style.paddingLeft);
    const right=outer.right-parseFloat(style.borderRightWidth)-parseFloat(style.paddingRight);
    return Math.max(Math.abs(inner.left-left),Math.abs(inner.right-right));
  },containerSelector)).toBeLessThanOrEqual(1);
}
